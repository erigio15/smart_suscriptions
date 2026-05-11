from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    smart_late_fee_product_id = fields.Many2one(
        'product.product',
        string='Producto para cargo por mora',
        config_parameter='smart_subscription_extra.late_fee_product_id',
        domain=[('type', '=', 'service')],
        help='Producto/servicio que se usará en la línea de la factura de mora. '
             'Debe ser de tipo Servicio.')

    smart_gcp_service_account_json = fields.Text(
        string='Service Account JSON (GCP)',
        config_parameter='smart_subscription_extra.gcp_sa_json',
        help='Contenido completo del archivo JSON del Service Account de GCP. '
             'Requiere permiso compute.instances.stop en el proyecto.')
