from datetime import timedelta

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_register_payment(self):
        if (not self.env.context.get('skip_smart_late_fee')
                and len(self) == 1
                and self.move_type == 'out_invoice'
                and self.state == 'posted'
                and self.payment_state not in ('paid', 'in_payment', 'reversed')):
            wizard_action = self._smart_check_late_fee_on_payment(fields.Date.today())
            if wizard_action:
                return wizard_action
        return super().action_register_payment()

    def _smart_check_late_fee_on_payment(self, payment_date):
        """
        Evalúa si la factura tiene mora al momento del pago.
        Retorna la acción del wizard si aplica mora, None si no aplica.
        """
        self.ensure_one()

        sub = self.invoice_line_ids.subscription_id[:1]
        if not sub:
            return None

        if not sub.smart_late_fee_value or sub.smart_late_fee_value <= 0:
            return None

        if not self.invoice_date:
            return None

        due_date = self.invoice_date + timedelta(days=sub.smart_invoice_due_days)

        if payment_date <= due_date:
            return None

        days_overdue = (payment_date - due_date).days

        if sub.smart_late_fee_type == 'fixed':
            fee_amount = sub.smart_late_fee_value * days_overdue
        else:
            fee_amount = (self.amount_untaxed * (sub.smart_late_fee_value / 100)) * days_overdue

        if fee_amount <= 0:
            return None

        wizard = self.env['smart.late.fee.wizard'].create({
            'subscription_id':   sub.id,
            'origin_invoice_id': self.id,
            'days_overdue':      days_overdue,
            'fee_amount':        fee_amount,
            'currency_id':       self.currency_id.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirmar cargo por mora',
            'res_model': 'smart.late.fee.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
