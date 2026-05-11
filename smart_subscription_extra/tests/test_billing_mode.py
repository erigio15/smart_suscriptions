from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestBillingMode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Test'})
        cls.plan = cls.env['sale.subscription.plan'].search([], limit=1)
        cls.product = cls.env['product.product'].create({
            'name': 'Servicio Test',
            'type': 'service',
            'invoice_policy': 'order',
            'recurring_invoice': True,
        })

    def _create_subscription(self, billing_mode):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'is_subscription': True,
            'subscription_state': '3_progress',
            'smart_billing_mode': billing_mode,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 100,
                'recurring_invoice': True,
            })],
        })
        order.action_confirm()
        return order

    def test_prepaid_description_contains_current_period(self):
        sub = self._create_subscription('prepaid')
        line = sub.order_line[0]
        invoice_vals = line._prepare_invoice_line()
        today = fields.Date.today()
        # La descripción pre-pago debe contener el año/mes vigente
        self.assertIn(str(today.year), invoice_vals.get('name', ''))

    def test_postpaid_description_contains_previous_period(self):
        sub = self._create_subscription('postpaid')
        line = sub.order_line[0]
        invoice_vals = line._prepare_invoice_line()
        today = fields.Date.today()
        last_month = today - relativedelta(months=1, day=1)
        expected_date = last_month.strftime('%d/%m/%Y')
        self.assertIn(expected_date, invoice_vals.get('name', ''))

    def test_postpaid_description_does_not_contain_current_month_start(self):
        sub = self._create_subscription('postpaid')
        line = sub.order_line[0]
        invoice_vals = line._prepare_invoice_line()
        today = fields.Date.today()
        current_month_start = today.replace(day=1).strftime('%d/%m/%Y')
        self.assertNotIn(current_month_start, invoice_vals.get('name', ''))

    def test_invoice_line_name_is_not_blocked(self):
        # El campo name de account.move.line no debe estar bloqueado (readonly)
        # Verificamos que puede escribirse directamente en el modelo
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Descripción original',
                'quantity': 1,
                'price_unit': 50,
            })],
        })
        line = move.invoice_line_ids[0]
        line.write({'name': 'Descripción editada manualmente'})
        self.assertEqual(line.name, 'Descripción editada manualmente')
