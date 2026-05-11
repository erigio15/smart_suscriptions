import json
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # --- Req. 1: Modalidad de facturación ---
    smart_billing_mode = fields.Selection([
        ('prepaid',  'Pre-pago (período vigente)'),
        ('postpaid', 'Post-pago (período anterior)'),
    ], string='Modalidad de facturación',
       default='prepaid',
       required=True,
       help='Pre-pago: la descripción cubre el mes actual. '
            'Post-pago: la descripción cubre el mes anterior al de emisión.')

    # --- Req. 2: Integración GCP ---
    smart_gcp_project_id = fields.Char(
        'GCP Project ID',
        help='ID del proyecto en Google Cloud Platform.')

    smart_gcp_zone = fields.Char(
        'GCP Zone',
        help='Zona de la instancia. Ej: us-central1-a')

    smart_gcp_instance_name = fields.Char(
        'Nombre de instancia VM',
        help='Nombre exacto de la VM en GCP.')

    smart_gcp_shutdown_day = fields.Integer(
        'Día de apagado por no pago',
        help='Día del mes (1-31) en que se apaga la VM si la factura más reciente no está pagada. '
             'El cron evalúa diariamente. Dejar en 0 para deshabilitar.',
        default=0)

    smart_gcp_shutdown_done = fields.Boolean(
        'Apagado ejecutado en ciclo actual',
        default=False,
        copy=False,
        help='Se marca True cuando el apagado se ejecuta en el ciclo mensual actual. '
             'Se resetea automáticamente al inicio de cada mes.')

    # --- Req. 3: Mora ---
    smart_late_fee_type = fields.Selection([
        ('fixed',   'Importe fijo diario (GTQ)'),
        ('percent', 'Porcentaje diario sobre el total de factura'),
    ], string='Tipo de mora',
       default='percent',
       help='Fijo: se cobra un importe fijo en GTQ por cada día de mora. '
            'Porcentaje: se cobra el % configurado sobre el total de la factura por cada día.')

    smart_late_fee_value = fields.Float(
        'Valor de mora',
        digits=(5, 4),
        help='Importe en GTQ (si tipo = Fijo) o porcentaje (si tipo = Porcentaje). '
             'Ejemplo: 5 = 5% diario.')

    smart_invoice_due_days = fields.Integer(
        'Días de plazo para pago',
        default=5,
        help='Días desde la emisión de la factura hasta su vencimiento. '
             'Ejemplo: 5 = factura del día 1 vence el día 6.')

    # --- Req. 4: Bloqueo de servidor ---
    smart_gcp_block_day = fields.Integer(
        'Día de bloqueo de servidor',
        help='Día del mes (1-31) en que se bloquea la VM si la factura más reciente '
             'no tiene pago completo. Dejar en 0 para deshabilitar.',
        default=0)

    smart_gcp_block_done = fields.Boolean(
        'Bloqueo ejecutado en ciclo actual',
        default=False,
        copy=False,
        help='Se marca True al ejecutarse el bloqueo. Se resetea automáticamente el día 1.')

    @api.constrains('smart_invoice_due_days')
    def _check_due_days(self):
        for rec in self:
            if rec.smart_invoice_due_days < 1:
                raise ValidationError(
                    'Los días de plazo para pago deben ser al menos 1.'
                )

    def _smart_get_latest_subscription_invoice(self):
        """Retorna la factura confirmada más reciente generada por esta suscripción."""
        return self.env['account.move'].search([
            ('id', 'in', self.invoice_ids.ids),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ], order='invoice_date desc', limit=1)

    def _smart_shutdown_gcp_vm(self, reason='no_payment'):
        """
        Detiene la VM de GCP asociada a la suscripción.
        :param reason: 'no_payment' (Req.2) | 'block_date' (Req.4)
        """
        try:
            from google.oauth2 import service_account
            from googleapiclient import discovery
        except ImportError:
            raise UserError(
                'Las librerías de Google Cloud no están instaladas. '
                'Ejecute: pip install google-api-python-client google-auth'
            )

        if not all([self.smart_gcp_project_id, self.smart_gcp_zone, self.smart_gcp_instance_name]):
            raise UserError(
                f'La suscripción "{self.name}" no tiene configurada la VM de GCP. '
                'Complete los campos: GCP Project ID, GCP Zone y Nombre de instancia VM.'
            )

        sa_json_str = self.env['ir.config.parameter'].sudo().get_param(
            'smart_subscription_extra.gcp_sa_json'
        )
        if not sa_json_str:
            raise UserError(
                'No hay credenciales de GCP configuradas. '
                'Vaya a Ajustes > Smart Business > GCP y configure el Service Account JSON.'
            )

        try:
            sa_info = json.loads(sa_json_str)
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=['https://www.googleapis.com/auth/compute']
            )
            service = discovery.build('compute', 'v1', credentials=credentials, cache_discovery=False)
            service.instances().stop(
                project=self.smart_gcp_project_id,
                zone=self.smart_gcp_zone,
                instance=self.smart_gcp_instance_name,
            ).execute()

            reason_label = {
                'no_payment': 'Factura sin pago en fecha de apagado configurada',
                'block_date': 'Fecha de bloqueo de servidor alcanzada con factura pendiente',
            }.get(reason, reason)

            self.message_post(
                body=f'⚠️ VM <b>{self.smart_gcp_instance_name}</b> apagada automáticamente. '
                     f'Motivo: {reason_label}.'
            )

        except Exception as e:
            self.message_post(
                body=f'❌ Error al intentar apagar VM <b>{self.smart_gcp_instance_name}</b>: {str(e)}'
            )
            # No relanzar — el cron no debe fallar por una VM individual

    @api.model
    def _smart_cron_gcp_shutdown_check(self):
        """
        Cron diario. Evalúa suscripciones con VM configurada donde hoy coincide
        con el día de apagado y la factura más reciente no está pagada.
        """
        today = fields.Date.today()
        today_day = today.day

        subscriptions = self.search([
            ('is_subscription', '=', True),
            ('smart_gcp_instance_name', '!=', False),
            ('smart_gcp_shutdown_day', '=', today_day),
            ('smart_gcp_shutdown_done', '=', False),
            ('subscription_state', 'not in', ['6_churn', '5_renewed']),
        ])

        for sub in subscriptions:
            latest_invoice = sub._smart_get_latest_subscription_invoice()
            if latest_invoice and latest_invoice.payment_state not in ('paid', 'in_payment'):
                sub._smart_shutdown_gcp_vm(reason='no_payment')
                sub.smart_gcp_shutdown_done = True

        if today_day == 1:
            self.search([('smart_gcp_shutdown_done', '=', True)]).write({
                'smart_gcp_shutdown_done': False
            })

    @api.model
    def _smart_cron_gcp_block_check(self):
        """
        Cron diario. Evalúa suscripciones con VM configurada donde hoy coincide
        con el día de bloqueo y la factura más reciente no tiene pago completo.
        """
        today = fields.Date.today()
        today_day = today.day

        subscriptions = self.search([
            ('is_subscription', '=', True),
            ('smart_gcp_instance_name', '!=', False),
            ('smart_gcp_block_day', '=', today_day),
            ('smart_gcp_block_done', '=', False),
            ('subscription_state', 'not in', ['6_churn', '5_renewed']),
        ])

        for sub in subscriptions:
            latest_invoice = sub._smart_get_latest_subscription_invoice()
            if latest_invoice and latest_invoice.payment_state not in ('paid', 'in_payment'):
                sub._smart_shutdown_gcp_vm(reason='block_date')
                sub.smart_gcp_block_done = True

        if today_day == 1:
            self.search([('smart_gcp_block_done', '=', True)]).write({
                'smart_gcp_block_done': False
            })


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if (not self.display_type
                and self.recurring_invoice
                and self.order_id.plan_id
                and self.order_id.smart_billing_mode == 'postpaid'):
            period_start, period_end = self._smart_postpaid_period()
            res['name'] = self._smart_build_period_description(period_start, period_end)
        return res

    def _smart_postpaid_period(self):
        today = fields.Date.today()
        period_start = today - relativedelta(months=1, day=1)
        period_end = today - relativedelta(day=1) - relativedelta(days=1)
        return period_start, period_end

    def _smart_build_period_description(self, period_start, period_end):
        product_name = self.product_id.name or ''
        duration = self.order_id.plan_id.billing_period_display
        date_from = period_start.strftime('%d/%m/%Y')
        date_to = period_end.strftime('%d/%m/%Y')
        return f"{product_name}\n{duration} {date_from} al {date_to}"
