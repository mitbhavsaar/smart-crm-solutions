# -*- coding: utf-8 -*-

from odoo import api, fields, models
import json
import logging

_logger = logging.getLogger(__name__)

class CrmLead(models.Model):
    _inherit = "crm.lead"
    
    name = fields.Char(
        'Opportunity', index='trigram', required=False,
        compute='_compute_name', readonly=False, store=True)
    opportunity_sequence = fields.Char(
        string="Opportunity Sequence",
        copy=False,
        readonly=True,
        index=True,
        help="Auto-generated sequence for opportunities."
    )
    material_line_ids = fields.One2many(
        "crm.material.line",
        "lead_id",
        string="Materials",
        copy=True,
    )
    
    company_contact_ids = fields.One2many(
        comodel_name="res.partner",
        inverse_name="parent_id",
        related="partner_id.child_ids",
        string="Company Contacts",
        readonly=True,
        store=False,
    )
    
    all_lines_priced = fields.Boolean(
        string="All Lines Priced",
        compute='_compute_all_lines_priced',
        store=True,
        help="True if all material lines have price greater than 0.0"
    )

    @api.depends('material_line_ids', 'material_line_ids.price')
    def _compute_all_lines_priced(self):
        """Compute if all material lines have price > 0.0"""
        for lead in self:
            if not lead.material_line_ids:
                # No lines means button should be hidden
                lead.all_lines_priced = False
            else:
                # Check if all lines have price > 0.0
                lead.all_lines_priced = all(
                    line.price > 0.0 for line in lead.material_line_ids
                )

    def action_new_quotation(self):
        """Create quotation with spreadsheet data transfer"""
        action = super(CrmLead, self).action_new_quotation()
        
        # Prepare order lines from material lines
        order_lines = []
        for line in self.material_line_ids:
            if line.product_id:
                line_vals = {
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity or 1.0,
                    'width': line.width or 0,
                    'thickness': line.thickness or 0,
                    'height': line.height or 0,
                    'length': line.length or 0,
                    'price_unit': line.price,
                    'name': line.product_id.name or "Product",
                }
                order_lines.append((0, 0, line_vals))
        
        # Find CRM spreadsheet
        crm_spreadsheet = self.env['crm.lead.spreadsheet'].search([
            ('lead_id', '=', self.id)
        ], limit=1)
        
        # Update context
        ctx = action.get('context', {}) or {}
        
        if order_lines:
            ctx['default_order_line'] = order_lines
        
        ctx.update({
            'default_opportunity_id': self.id,
            'default_origin': self.name,
            'from_crm_lead': True,
            'crm_has_spreadsheet': bool(crm_spreadsheet and crm_spreadsheet.raw_spreadsheet_data),
            'crm_lead_id': self.id,
        })
        
        action['context'] = ctx
        return action

    def _convert_crm_spreadsheet_to_sales(self, crm_spreadsheet, sale_order):
        """Convert CRM spreadsheet data to Sales format - IMPROVED MULTI-SHEET SUPPORT"""
        self.ensure_one()
        
        if not crm_spreadsheet.raw_spreadsheet_data:
            return False

        try:
            crm_data = json.loads(crm_spreadsheet.raw_spreadsheet_data)
            
            # reate line ID mapping for ALL material lines
            line_mapping = self._create_complete_line_id_mapping(sale_order)
            if not line_mapping:
                return False
            
            
            # Create comprehensive ID mapping
            id_mapping = {}
            for crm_id, sales_id in line_mapping.items():
                id_mapping[str(crm_id)] = str(sales_id)
                id_mapping[f"sheet_{crm_id}"] = f"sheet_sales_{sales_id}"
            
            #  Enhanced field mapping
            FIELD_MAP = {
                'product_template_id': 'product_id',
                'quantity': 'product_uom_qty', 
                'price': 'price_unit',
                'width': 'width',
                'height': 'height', 
                'length': 'length',
                'thickness': 'thickness',
                'raw_material': 'raw_material',

            }
            
            #  Transform ALL lists from CRM
            sales_lists = {}
            crm_lists = crm_data.get('lists', {})
            
            
            for old_list_id, list_config in crm_lists.items():
                try:
                    # Handle both integer and string list IDs
                    if old_list_id.isdigit():
                        crm_line_id = int(old_list_id)
                        sales_line_id = line_mapping.get(crm_line_id)
                    else:
                        # For non-numeric list IDs, try to extract numeric part
                        import re
                        numbers = re.findall(r'\d+', old_list_id)
                        if numbers:
                            crm_line_id = int(numbers[0])
                            sales_line_id = line_mapping.get(crm_line_id)
                        else:
                            sales_line_id = None
                    
                    if sales_line_id:
                        old_columns = list_config.get('columns', [])
                        new_columns = []
                        for col in old_columns:
                            new_col = FIELD_MAP.get(col, col)
                            new_columns.append(new_col)
                        
                        # Create complete list configuration
                        sales_lists[str(sales_line_id)] = {
                            'id': str(sales_line_id),
                            'model': 'sale.order.line',
                            'columns': new_columns,
                            'domain': [['id', '=', sales_line_id]],
                            'sheetId': f"sheet_sales_{sales_line_id}",
                            'name': list_config.get('name', f'Sales Item {sales_line_id}'),
                            'context': list_config.get('context', {}),
                            'orderBy': list_config.get('orderBy', []),
                            'fieldMatching': {
                                'order_line': {'chain': 'order_id', 'type': 'many2one'}
                            },
                        }
                    else:
                        # Preserve lists that don't map to specific lines
                        sales_lists[old_list_id] = list_config
                        
                except (ValueError, KeyError, AttributeError) as e:
                    # Preserve the list even if there's an error
                    sales_lists[old_list_id] = list_config
                    continue
            
            #  Process ALL sheets from CRM
            sales_sheets = []
            crm_sheets = crm_data.get('sheets', [])
            
            
            for sheet in crm_sheets:
                old_sheet_id = sheet.get('id', '')
                
                # Handle line-specific sheets
                if old_sheet_id.startswith('sheet_'):
                    try:
                        sheet_number = old_sheet_id.replace('sheet_', '')
                        if sheet_number.isdigit():
                            crm_line_id = int(sheet_number)
                            sales_line_id = line_mapping.get(crm_line_id)
                            
                            if sales_line_id:
                                new_sheet = self._create_complete_sheet_copy(
                                    sheet, sales_line_id, id_mapping, FIELD_MAP
                                )
                                sales_sheets.append(new_sheet)
                            else:
                                sales_sheets.append(sheet)
                        else:
                            sales_sheets.append(sheet)
                            
                    except (ValueError, KeyError) as e:
                        sales_sheets.append(sheet)
                        continue
                else:
                    sales_sheets.append(sheet)
            
            #  Build COMPLETE sales data structure
            sales_data = {
                'lists': sales_lists,
                'sheets': sales_sheets,
                'globalFilters': crm_data.get('globalFilters', []),
                'pivots': crm_data.get('pivots', {}),
                'odooVersion': crm_data.get('odooVersion', 12),
                'revisionId': crm_data.get('revisionId', 'START_REVISION'),
                'settings': crm_data.get('settings', {}),
                'chartConfigs': crm_data.get('chartConfigs', {}),
                'customCurrencyFormats': crm_data.get('customCurrencyFormats', []),
                **{k: v for k, v in crm_data.items() if k not in [
                    'lists', 'sheets', 'globalFilters', 'pivots', 'odooVersion', 
                    'revisionId', 'settings', 'chartConfigs', 'customCurrencyFormats'
                ]}
            }            
            return json.dumps(sales_data)
            
        except Exception as e:
            return False
        


    def _create_complete_sheet_copy(self, original_sheet, sales_line_id, id_mapping, field_map):
        """Create a complete copy of a sheet with updated references"""
        # Copy ALL sheet properties
        new_sheet = original_sheet.copy()
        
        # Update sheet ID
        new_sheet['id'] = f"sheet_sales_{sales_line_id}"
        new_sheet['name'] = original_sheet.get('name', f'Sales Item {sales_line_id}')[:31]
        
        # Update cells with formulas and field references
        new_cells = {}
        for cell_ref, cell_data in original_sheet.get('cells', {}).items():
            new_cell_data = cell_data.copy()
            
            # Update formulas with new IDs and field names
            content = cell_data.get('content', '')
            if content and isinstance(content, str):
                updated_content = self._update_formula_references(content, id_mapping, field_map)
                new_cell_data['content'] = updated_content
            
            new_cells[cell_ref] = new_cell_data
        
        new_sheet['cells'] = new_cells
        
        # Update fieldSyncs with new list IDs and field names
        new_field_syncs = {}
        for cell_ref, field_sync in original_sheet.get('fieldSyncs', {}).items():
            new_field_sync = field_sync.copy()
            old_list_id = field_sync.get('listId')
            
            if old_list_id and old_list_id in id_mapping:
                new_field_sync['listId'] = id_mapping[old_list_id]
            
            # Update field name in fieldSync
            old_field_name = field_sync.get('fieldName')
            if old_field_name and old_field_name in field_map:
                new_field_sync['fieldName'] = field_map[old_field_name]
            
            new_field_syncs[cell_ref] = new_field_sync
        
        new_sheet['fieldSyncs'] = new_field_syncs
        
        return new_sheet

    def _update_formula_references(self, content, id_mapping, field_map):
        """Update formula references to new list IDs and field names"""
        updated_content = content
        
        # Replace list IDs in ODOO formulas
        for old_id, new_id in id_mapping.items():
            # Handle ODOO.LIST.HEADER references
            updated_content = updated_content.replace(
                f'ODOO.LIST.HEADER({old_id},', 
                f'ODOO.LIST.HEADER({new_id},'
            )
            # Handle ODOO.LIST references
            updated_content = updated_content.replace(
                f'ODOO.LIST({old_id},', 
                f'ODOO.LIST({new_id},'
            )
            # Handle direct ID references
            updated_content = updated_content.replace(
                f'"{old_id}"', 
                f'"{new_id}"'
            )
        
        # Replace field names in formulas
        for old_field, new_field in field_map.items():
            # Handle quoted field names
            updated_content = updated_content.replace(f'"{old_field}"', f'"{new_field}"')
            # Handle unquoted field names in specific patterns
            updated_content = updated_content.replace(f",{old_field},", f",{new_field},")
            updated_content = updated_content.replace(f",{old_field})", f",{new_field})")
        
        return updated_content

    def _create_complete_line_id_mapping(self, sale_order):
        """Create COMPLETE mapping for ALL material lines"""
        self.ensure_one()
        mapping = {}
        
        material_lines = self.material_line_ids.sorted('id')
        order_lines = sale_order.order_line.sorted('id')
        
        
        # Strategy 1: Exact match by product and ALL dimensions
        used_order_lines = set()
        used_material_lines = set()
        
        for mat_line in material_lines:
            if mat_line.id in used_material_lines:
                continue
                
            best_match = None
            best_score = 0
            
            for order_line in order_lines:
                if order_line.id in used_order_lines:
                    continue
                
                score = 0
                # Product match (highest priority)
                if order_line.product_id == mat_line.product_id:
                    score += 10
                
                # Dimension matches
                if float(order_line.width or 0) == float(mat_line.width or 0):
                    score += 2
                if float(order_line.thickness or 0) == float(mat_line.thickness or 0):
                    score += 2
                if float(order_line.height or 0) == float(mat_line.height or 0):
                    score += 2
                if float(order_line.length or 0) == float(mat_line.length or 0):
                    score += 2
                if float(order_line.product_uom_qty or 0) == float(mat_line.quantity or 0):
                    score += 1
                
                if score > best_score:
                    best_score = score
                    best_match = order_line
            
            if best_match and best_score >= 3:  
                mapping[mat_line.id] = best_match.id
                used_order_lines.add(best_match.id)
                used_material_lines.add(mat_line.id)
        
        # Strategy 2: Product-only match for remaining lines
        remaining_material = [ml for ml in material_lines if ml.id not in used_material_lines]
        remaining_orders = [ol for ol in order_lines if ol.id not in used_order_lines]
        
        for mat_line in remaining_material:
            for order_line in remaining_orders:
                if order_line.product_id == mat_line.product_id:
                    mapping[mat_line.id] = order_line.id
                    used_order_lines.add(order_line.id)
                    remaining_orders.remove(order_line)
                    break
        
        # Strategy 3: Sequential mapping for any remaining lines
        final_material = [ml for ml in material_lines if ml.id not in used_material_lines]
        final_orders = [ol for ol in order_lines if ol.id not in used_order_lines]
        
        min_count = min(len(final_material), len(final_orders))
        for i in range(min_count):
            mapping[final_material[i].id] = final_orders[i].id
        
        # Strategy 4: Create missing order lines if needed
        if len(mapping) < len(material_lines):
            unmapped_material = [ml for ml in material_lines if ml.id not in mapping]
            
            for mat_line in unmapped_material:
                new_order_line = self.env['sale.order.line'].create({
                    'order_id': sale_order.id,
                    'product_id': mat_line.product_id.id,
                    'product_uom_qty': mat_line.quantity or 1.0,
                    'price_unit': mat_line.price or mat_line.product_id.list_price,
                    'width': mat_line.width or 0,
                    'height': mat_line.height or 0,
                    'length': mat_line.length or 0,
                    'thickness': mat_line.thickness or 0,
                    'raw_material': mat_line.raw_material or '',

                    'name': mat_line.product_id.name or "Product",
                })
                mapping[mat_line.id] = new_order_line.id
        
        return mapping
    
    def _create_sales_spreadsheet_with_data(self, sale_order):
        """Create sales spreadsheet with converted CRM data - FULLY FIXED"""
        self.ensure_one()
        
        _logger.info(f"\n🔵 [CREATE SALES SPREADSHEET] Starting for Lead {self.id}, Order {sale_order.id}")
        
        # ✅ STEP 1: Find CRM spreadsheet
        crm_spreadsheet = self.env['crm.lead.spreadsheet'].search([
            ('lead_id', '=', self.id)
        ], limit=1)
        
        if not crm_spreadsheet:
            _logger.warning(f"⚠️ No CRM spreadsheet found for lead {self.id}")
            return False
            
        if not crm_spreadsheet.exists():
            _logger.warning(f"⚠️ CRM spreadsheet was deleted for lead {self.id}")
            return False
            
        if not crm_spreadsheet.raw_spreadsheet_data:
            _logger.warning(f"⚠️ CRM spreadsheet {crm_spreadsheet.id} has no data")
            return False
        
        _logger.info(f"✅ Found CRM spreadsheet: {crm_spreadsheet.id}")
        
        # ✅ STEP 2: Convert CRM data to Sales format
        try:
            sales_data_json = self._convert_crm_spreadsheet_to_sales(crm_spreadsheet, sale_order)
        except Exception as conv_error:
            _logger.error(f"❌ CRM data conversion failed: {conv_error}", exc_info=True)
            return False
            
        if not sales_data_json:
            _logger.warning(f"⚠️ CRM data conversion returned empty")
            return False
        
        _logger.info(f"✅ Converted CRM data to Sales format ({len(sales_data_json)} chars)")
        
        # ✅ STEP 3: Check if Sales spreadsheet already exists
        existing_spreadsheet = self.env['sale.order.spreadsheet'].search([
            ('order_id', '=', sale_order.id)
        ], limit=1)
        
        if existing_spreadsheet:
            _logger.info(f"ℹ️ Sales spreadsheet {existing_spreadsheet.id} already exists, updating...")
            try:
                existing_spreadsheet.raw_spreadsheet_data = sales_data_json
                
                # Link CRM spreadsheet
                if crm_spreadsheet.exists():
                    crm_spreadsheet.sale_id = sale_order.id
                    
                _logger.info(f"✅ Updated existing spreadsheet {existing_spreadsheet.id}")
                return existing_spreadsheet
                
            except Exception as e:
                _logger.error(f"❌ Failed to update spreadsheet: {e}", exc_info=True)
                return False
        
        # ✅ STEP 4: Create new Sales spreadsheet
        try:
            sales_spreadsheet = self.env['sale.order.spreadsheet'].create({
                'name': f"{sale_order.name} - Calculator",
                'order_id': sale_order.id,
                'raw_spreadsheet_data': sales_data_json,
            })
            
            # Commit to ensure it exists
            self.env.cr.commit()
            
            _logger.info(f"✅ Created Sales spreadsheet: {sales_spreadsheet.id}")
            
            # ✅ STEP 5: Link CRM spreadsheet to Sale Order
            if crm_spreadsheet.exists():
                try:
                    crm_spreadsheet.sale_id = sale_order.id
                    self.env.cr.commit()
                    _logger.info(f"✅ Linked CRM spreadsheet {crm_spreadsheet.id} to Sale {sale_order.id}")
                except Exception as e:
                    _logger.error(f"⚠️ Failed to link CRM spreadsheet: {e}")
                    # Don't fail the whole operation
            
            return sales_spreadsheet
            
        except Exception as e:
            _logger.error(f"❌ Failed to create Sales spreadsheet: {e}", exc_info=True)
            # Rollback if creation failed
            self.env.cr.rollback()
            return False

    @api.model
    def create(self, vals):
        """Opportunity sequence generation"""
        seq_obj = self.env["ir.sequence"]
        seq_code = "crm.opportunity.custom.seq"

        lead = super().create(vals)

        is_opportunity = (vals.get("type") in (False, "opportunity")) or (lead.type in (False, "opportunity"))
        if is_opportunity and not lead.opportunity_sequence:
            lead.opportunity_sequence = seq_obj.next_by_code(seq_code) or False

        return lead

    def write(self, vals):
        ctx = self.env.context
        if 'material_line_ids' in vals and not ctx.get('from_template'):
            filtered_lines = []
            for command in vals['material_line_ids']:
                if command[0] == 0 and command[2].get('product_id'):
                    filtered_lines.append(command)
                elif command[0] != 0:
                    filtered_lines.append(command)
            vals['material_line_ids'] = filtered_lines
        return super().write(vals)