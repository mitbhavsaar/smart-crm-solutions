from datetime import datetime
from odoo import http
from odoo.http import request

class ProductionDeliveryController(http.Controller):

    @http.route('/production/delivery_date', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def delivery_date_popup(self, lead_id=None, delivery_date=None, **post):
        if not lead_id:
            return request.not_found()

        try:
            lead_id = int(lead_id)
        except (ValueError, TypeError):
            return request.not_found()

        lead = request.env['crm.lead'].sudo().browse(lead_id)
        if not lead.exists() or not lead.ask_for_delivery_date:
            return request.not_found()

        if request.httprequest.method == 'POST':
            if lead.delivery_date:
                return request.render('crm_customisation.delivery_date_already_set', {'lead': lead})

            try:
                date_obj = datetime.strptime(delivery_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return request.not_found()

            lead.write({'delivery_date': date_obj})

            # ✅ Optional: Post internal message
            lead.message_post(body=f"Delivery date set by Production Incharge: {date_obj}")

            # ✅ Redirect to the lead form in backend
            return request.redirect(f"/web#id={lead.id}&model=crm.lead&view_type=form")

        # ✅ Handle GET: show the date input form
        return request.render('crm_customisation.delivery_date_portal_template', {
            'lead': lead,
        })
