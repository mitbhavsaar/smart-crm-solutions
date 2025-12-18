from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    enable_crm_quotation_templates = fields.Boolean(
        string="Enable CRM Quotation Templates"
    )

    crm_quotation_template_id = fields.Many2one(
        'crm.quotation.template',
        string="CRM Quotation Template",
    )
