from odoo import fields, models
from odoo.exceptions import UserError


class SmartLateFeeWizard(models.TransientModel):
    _name = 'smart.late.fee.wizard'
    _description = 'Confirmación de cargo por mora'

    subscription_id   = fields.Many2one('sale.order', readonly=True,
                                         string='Suscripción')
    origin_invoice_id = fields.Many2one('account.move', readonly=True,
                                         string='Factura de origen')
    days_overdue      = fields.Integer('Días en mora', readonly=True)
    fee_amount        = fields.Float('Monto de mora calculado', readonly=True,
                                      digits='Account')
    currency_id       = fields.Many2one('res.currency', readonly=True)

    def action_confirm(self):
        """Genera la factura adicional de mora."""
        self.ensure_one()

        product_id_str = self.env['ir.config.parameter'].sudo().get_param(
            'smart_subscription_extra.late_fee_product_id'
        )
        if not product_id_str:
            raise UserError(
                'No hay un producto de mora configurado. '
                'Vaya a Ajustes > Smart Business > Suscripciones y configure '
                'el Producto para cargo por mora.'
            )

        product = self.env['product.product'].browse(int(product_id_str))
        if not product.exists():
            raise UserError(
                'El producto de mora configurado ya no existe. '
                'Reconfigure el producto en Ajustes > Smart Business > Suscripciones.'
            )

        sub = self.subscription_id
        origin = self.origin_invoice_id

        move_vals = {
            'move_type':      'out_invoice',
            'partner_id':     origin.partner_id.id,
            'invoice_origin': f'Mora — {origin.name}',
            'narration': (
                f'Cargo por mora: {self.days_overdue} día(s) de retraso '
                f'en factura {origin.name}.'
            ),
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': (
                    f'Mora por {self.days_overdue} día(s) — '
                    f'Factura {origin.name}'
                ),
                'quantity':   1,
                'price_unit': self.fee_amount,
                'subscription_id': sub.id,
            })],
        }
        late_fee_invoice = self.env['account.move'].create(move_vals)

        origin.message_post(
            body=f'Se generó factura de mora <b>{late_fee_invoice.name or "(borrador)"}</b> '
                 f'por {self.days_overdue} día(s) de retraso. '
                 f'Monto: {self.fee_amount:.2f} {self.currency_id.name}.'
        )

        return {
            'type':      'ir.actions.act_window',
            'name':      'Factura de mora',
            'res_model': 'account.move',
            'res_id':    late_fee_invoice.id,
            'view_mode': 'form',
            'target':    'current',
        }

    def action_skip(self):
        """El usuario omite el cargo por mora para este pago."""
        self.ensure_one()
        self.origin_invoice_id.message_post(
            body='Cargo por mora omitido manualmente por el usuario.'
        )
        return {'type': 'ir.actions.act_window_close'}
