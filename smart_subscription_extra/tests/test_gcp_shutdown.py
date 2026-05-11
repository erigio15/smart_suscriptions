from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestGcpShutdown(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente GCP Test'})
        cls.plan = cls.env['sale.subscription.plan'].search([], limit=1)
        cls.product = cls.env['product.product'].create({
            'name': 'Servicio GCP',
            'type': 'service',
            'invoice_policy': 'order',
            'recurring_invoice': True,
        })
        cls.today = fields.Date.today()

    def _create_subscription_with_vm(self, shutdown_day=None, block_day=None, shutdown_done=False, block_done=False):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'is_subscription': True,
            'subscription_state': '3_progress',
            'smart_gcp_project_id': 'test-project',
            'smart_gcp_zone': 'us-central1-a',
            'smart_gcp_instance_name': 'test-instance',
            'smart_gcp_shutdown_day': shutdown_day or 0,
            'smart_gcp_shutdown_done': shutdown_done,
            'smart_gcp_block_day': block_day or 0,
            'smart_gcp_block_done': block_done,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 100,
                'recurring_invoice': True,
            })],
        })
        order.action_confirm()
        return order

    def _create_unpaid_invoice(self, sub):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Servicio',
                'quantity': 1,
                'price_unit': 100,
                'subscription_id': sub.id,
            })],
        })
        invoice.action_post()
        return invoice

    def test_cron_shuts_down_vm_when_invoice_unpaid_on_shutdown_day(self):
        sub = self._create_subscription_with_vm(shutdown_day=self.today.day)
        self._create_unpaid_invoice(sub)

        with patch.object(type(sub), '_smart_shutdown_gcp_vm') as mock_shutdown:
            self.env['sale.order']._smart_cron_gcp_shutdown_check()
            mock_shutdown.assert_called_once_with(reason='no_payment')

        sub.invalidate_recordset()
        self.assertTrue(sub.smart_gcp_shutdown_done)

    def test_cron_does_not_shutdown_twice_in_same_cycle(self):
        sub = self._create_subscription_with_vm(
            shutdown_day=self.today.day,
            shutdown_done=True,
        )
        self._create_unpaid_invoice(sub)

        with patch.object(type(sub), '_smart_shutdown_gcp_vm') as mock_shutdown:
            self.env['sale.order']._smart_cron_gcp_shutdown_check()
            mock_shutdown.assert_not_called()

    def test_cron_resets_shutdown_done_on_first_of_month(self):
        sub = self._create_subscription_with_vm(shutdown_done=True)
        # Simular que hoy es día 1
        with patch('odoo.fields.Date.today', return_value=self.today.replace(day=1)):
            self.env['sale.order']._smart_cron_gcp_shutdown_check()

        sub.invalidate_recordset()
        self.assertFalse(sub.smart_gcp_shutdown_done)

    def test_cron_ignores_subscriptions_without_instance_name(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'plan_id': self.plan.id,
            'is_subscription': True,
            'subscription_state': '3_progress',
            'smart_gcp_shutdown_day': self.today.day,
        })
        order.action_confirm()
        self._create_unpaid_invoice(order)

        with patch.object(type(order), '_smart_shutdown_gcp_vm') as mock_shutdown:
            self.env['sale.order']._smart_cron_gcp_shutdown_check()
            mock_shutdown.assert_not_called()

    def test_cron_does_not_evaluate_invoices_from_other_subscriptions(self):
        sub1 = self._create_subscription_with_vm(shutdown_day=self.today.day)
        sub2 = self._create_subscription_with_vm()
        # Crear factura sin pago para sub2, no para sub1
        self._create_unpaid_invoice(sub2)

        with patch.object(type(sub1), '_smart_shutdown_gcp_vm') as mock_shutdown:
            self.env['sale.order']._smart_cron_gcp_shutdown_check()
            # sub1 no tiene facturas, no debe apagarse
            mock_shutdown.assert_not_called()
