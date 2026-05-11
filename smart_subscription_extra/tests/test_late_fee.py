from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLateFee(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Mora Test'})
        cls.plan = cls.env['sale.subscription.plan'].search([], limit=1)
        cls.product_service = cls.env['product.product'].create({
            'name': 'Servicio Mora',
            'type': 'service',
            'invoice_policy': 'order',
        })
        cls.product_late_fee = cls.env['product.product'].create({
            'name': 'Cargo por Mora',
            'type': 'service',
        })
        cls.env['ir.config.parameter'].sudo().set_param(
            'smart_subscription_extra.late_fee_product_id',
            str(cls.product_late_fee.id),
        )

    def _create_subscription(self, late_fee_type='percent', late_fee_value=5.0, due_days=5):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'is_subscription': True,
            'subscription_state': '3_progress',
            'smart_late_fee_type': late_fee_type,
            'smart_late_fee_value': late_fee_value,
            'smart_invoice_due_days': due_days,
            'order_line': [(0, 0, {
                'product_id': self.product_service.id,
                'product_uom_qty': 1,
                'price_unit': 1000,
                'recurring_invoice': True,
            })],
        })
        order.action_confirm()
        return order

    def _create_posted_invoice(self, sub, invoice_date):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': invoice_date,
            'invoice_line_ids': [(0, 0, {
                'name': 'Servicio',
                'quantity': 1,
                'price_unit': 1000,
                'subscription_id': sub.id,
            })],
        })
        invoice.action_post()
        return invoice

    def test_late_payment_percent_generates_wizard(self):
        sub = self._create_subscription(late_fee_type='percent', late_fee_value=5.0, due_days=5)
        invoice_date = date(2025, 1, 1)
        invoice = self._create_posted_invoice(sub, invoice_date)

        # Pago 3 días después del vencimiento (día 9, vence día 6)
        payment_date = invoice_date + timedelta(days=8)
        days_overdue = 3
        expected_fee = (1000.0 * 0.05) * days_overdue  # amount_untaxed * 5% * 3 días

        result = invoice._smart_check_late_fee_on_payment(payment_date)

        self.assertIsNotNone(result)
        self.assertEqual(result['res_model'], 'smart.late.fee.wizard')
        wizard = self.env['smart.late.fee.wizard'].browse(result['res_id'])
        self.assertEqual(wizard.days_overdue, days_overdue)
        self.assertAlmostEqual(wizard.fee_amount, expected_fee, places=2)

    def test_on_time_payment_does_not_generate_wizard(self):
        sub = self._create_subscription(late_fee_type='percent', late_fee_value=5.0, due_days=5)
        invoice_date = date(2025, 1, 1)
        invoice = self._create_posted_invoice(sub, invoice_date)

        # Pago a tiempo (dentro del plazo)
        payment_date = invoice_date + timedelta(days=5)
        result = invoice._smart_check_late_fee_on_payment(payment_date)

        self.assertIsNone(result)

    def test_confirm_wizard_creates_late_fee_invoice(self):
        sub = self._create_subscription(late_fee_type='percent', late_fee_value=5.0, due_days=5)
        invoice_date = date(2025, 1, 1)
        invoice = self._create_posted_invoice(sub, invoice_date)

        payment_date = invoice_date + timedelta(days=8)
        result = invoice._smart_check_late_fee_on_payment(payment_date)
        wizard = self.env['smart.late.fee.wizard'].browse(result['res_id'])

        action = wizard.action_confirm()

        self.assertEqual(action['res_model'], 'account.move')
        late_fee_invoice = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(late_fee_invoice.state, 'draft')
        self.assertEqual(late_fee_invoice.move_type, 'out_invoice')
        self.assertTrue(late_fee_invoice.invoice_line_ids)
        self.assertEqual(
            late_fee_invoice.invoice_line_ids[0].subscription_id.id,
            sub.id,
        )

    def test_late_fee_invoice_uses_configured_product(self):
        sub = self._create_subscription(late_fee_type='fixed', late_fee_value=50.0, due_days=5)
        invoice_date = date(2025, 1, 1)
        invoice = self._create_posted_invoice(sub, invoice_date)

        payment_date = invoice_date + timedelta(days=7)
        result = invoice._smart_check_late_fee_on_payment(payment_date)
        wizard = self.env['smart.late.fee.wizard'].browse(result['res_id'])
        action = wizard.action_confirm()

        late_fee_invoice = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(
            late_fee_invoice.invoice_line_ids[0].product_id.id,
            self.product_late_fee.id,
        )

    def test_due_days_below_one_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            self.env['sale.order'].create({
                'partner_id': self.partner.id,
                'plan_id': self.plan.id,
                'is_subscription': True,
                'smart_invoice_due_days': 0,
            })

    def test_invoice_without_subscription_does_not_generate_wizard(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date(2025, 1, 1),
            'invoice_line_ids': [(0, 0, {
                'name': 'Venta simple',
                'quantity': 1,
                'price_unit': 500,
            })],
        })
        invoice.action_post()

        result = invoice._smart_check_late_fee_on_payment(date(2025, 2, 1))
        self.assertIsNone(result)
