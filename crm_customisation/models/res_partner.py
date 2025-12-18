# -*- coding: utf-8 -*-
import requests
import logging
import re
from functools import lru_cache
from odoo import models, api, _

_logger = logging.getLogger(__name__)

# Global session (connection reuse = faster)
_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0"})

@lru_cache(maxsize=5000)
def _fetch_pin_info(zip_code):
    """Fetch postal info with caching for speed."""
    url = f'https://api.postalpincode.in/pincode/{zip_code}'
    try:
        r = _session.get(url, timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        _logger.error("PIN API failed for %s: %s", zip_code, e)
        return None


class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        context = self.env.context or {}
        args = args or []
        if context.get('res_partner_search_mode') == 'customer':
            args += [('parent_id', '=', False), ('is_company', '=', True)]

        return super().name_search(name=name, args=args, operator=operator, limit=limit)

    # ------------------------------ 
    # Auto-fill city & state from ZIP 
    # ------------------------------
    @api.onchange('zip', 'street', 'street2')
    def _onchange_zip(self):
        """Auto-fill city and state from pincode (generic, all India)."""

        if not (self.zip and len(self.zip) == 6 and self.zip.isdigit()):
            return

        # Reset values
        self.city = False
        self.state_id = False

        data = _fetch_pin_info(self.zip)
        if not data or not (isinstance(data, list) and data and data[0].get('Status') == 'Success'):
            return

        post_offices = data[0].get('PostOffice') or []
        if not post_offices:
            return

        # Normalize function
        def norm(s):
            if not s:
                return ''
            return re.sub(r'\s+', ' ', str(s).strip().lower())

        street_vals = ' '.join(filter(None, [self.street or '', self.street2 or '']))
        street_norm = norm(street_vals)

        chosen = None

        # Case 1: Street is empty → fallback to district
        if not street_norm:
            district = post_offices[0].get('District') or ''
            if district:
                self.city = district
            # Apply state as well
            state_name = post_offices[0].get('State')
            if state_name and self.country_id:
                state = self.env['res.country.state'].search([
                    ('name', '=', state_name),
                    ('country_id', '=', self.country_id.id)
                ], limit=1)
                if state:
                    self.state_id = state.id
            return

        # Case 2: Street provided → try matches
        for po in post_offices:
            if norm(po.get('Name')) and norm(po.get('Name')) in street_norm:
                chosen = po
                break

        if not chosen:
            for po in post_offices:
                if norm(po.get('Block')) and norm(po.get('Block')) in street_norm:
                    chosen = po
                    break

        if not chosen:
            for po in post_offices:
                if norm(po.get('District')) and norm(po.get('District')) in street_norm:
                    chosen = po
                    break

        # Fallbacks
        if not chosen:
            if len(post_offices) == 1:
                chosen = post_offices[0]
            else:
                # multiple options, no clear match → default to district
                district = post_offices[0].get('District') or ''
                self.city = district
                state_name = post_offices[0].get('State')
                if state_name and self.country_id:
                    state = self.env['res.country.state'].search([
                        ('name', '=', state_name),
                        ('country_id', '=', self.country_id.id)
                    ], limit=1)
                    if state:
                        self.state_id = state.id
                _logger.warning("Multiple localities found for PIN=%s, no street match → using District=%s", self.zip, district)
                return

        # Apply chosen locality
        if chosen:
            self._apply_postoffice(chosen)


    def _apply_postoffice(self, po):
        """Helper to set fields from a single PostOffice dict."""
        if not po:
            return

        district = po.get('District') or ''
        state_name = po.get('State')
        name = po.get('Name') or ''

        # City = PostOffice name (preferred), else District
        self.city = name or district

        if state_name and self.country_id:
            state = self.env['res.country.state'].search([
                ('name', '=', state_name),
                ('country_id', '=', self.country_id.id)
            ], limit=1)
            if state:
                self.state_id = state.id
