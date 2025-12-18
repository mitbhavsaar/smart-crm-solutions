from odoo.http import Controller, request, route
from odoo import http
import base64
import logging
import traceback

_logger = logging.getLogger(__name__)


class ProductConfiguratorController(Controller):

    @route('/crm_product_configurator/get_values', type='json', auth='user')
    def get_product_configurator_values(
        self,
        product_template_id,
        quantity,
        currency_id=None,
        product_uom_id=None,
        company_id=None,
        ptav_ids=None,
        only_main_product=False,
    ):
        """ Return all product information needed for the product configurator.
        """
        if company_id:
            request.update_context(allowed_company_ids=[company_id])

        product_template = request.env['product.template'].browse(product_template_id)
        combination = request.env['product.template.attribute.value']

        if ptav_ids:
            combination = request.env['product.template.attribute.value'].browse(ptav_ids).filtered(
                lambda ptav: ptav.product_tmpl_id.id == product_template_id
            )
            # Set missing attributes (unsaved no_variant attributes, or new attribute on existing product)
            unconfigured_ptals = (
                product_template.attribute_line_ids - combination.attribute_line_id
            ).filtered(lambda ptal: ptal.attribute_id.display_type != 'multi')
            combination += unconfigured_ptals.mapped(
                lambda ptal: ptal.product_template_value_ids._only_active()[:1]
            )

        if not combination:
            combination = product_template._get_first_possible_combination()

        return dict(
            products=[
                dict(
                    **self._get_product_information(
                        product_template,
                        combination,
                        currency_id,
                        quantity=quantity,
                        product_uom_id=product_uom_id,
                    ),
                    parent_product_tmpl_ids=[],
                )
            ],
            optional_products=[
                dict(
                    **self._get_product_information(
                        optional_product_template,
                        optional_product_template._get_first_possible_combination(
                            parent_combination=combination
                        ),
                        currency_id,
                        # giving all the ptav of the parent product to get all the exclusions
                        parent_combination=product_template.attribute_line_ids.product_template_value_ids,
                    ),
                    parent_product_tmpl_ids=[product_template.id],
                )
                for optional_product_template in product_template.optional_product_ids
            ]
            if not only_main_product
            else [],
        )

    @route('/crm_product_configurator/create_product', type='json', auth='user')
    def purchase_product_configurator_create_product(self, product_template_id, combination):
        """ Create the product when there is a dynamic attribute in the combination.
        """
        product_template = request.env['product.template'].browse(product_template_id)
        combination = request.env['product.template.attribute.value'].browse(combination)
        product = product_template._create_product_variant(combination)
        return product.id

    @route('/crm_product_configurator/update_combination', type='json', auth='user')
    def purchase_product_configurator_update_combination(self, **kwargs):
        """ Return the updated combination information. """
        product_template_id = kwargs.get('product_template_id')
        combination = kwargs.get('combination')
        quantity = kwargs.get('quantity')
        currency_id = kwargs.get('currency_id')
        product_uom_id = kwargs.get('product_uom_id')
        company_id = kwargs.get('company_id')

        if company_id:
            request.update_context(allowed_company_ids=[company_id])

        product_template = request.env['product.template'].browse(product_template_id)
        product_uom = request.env['uom.uom'].browse(product_uom_id)
        currency = request.env['res.currency'].browse(currency_id)
        combination = request.env['product.template.attribute.value'].browse(combination)
        product = product_template._get_variant_for_combination(combination)

        return self._get_basic_product_information(
            product or product_template,
            combination,
            quantity=quantity or 0.0,
            uom=product_uom,
            currency=currency,
        )

    @route('/crm_product_configurator/get_optional_products', type='json', auth='user')
    def purchase_product_configurator_get_optional_products(
        self,
        product_template_id,
        combination,
        parent_combination,
        currency_id=None,
        company_id=None,
    ):
        """ Return information about optional products for the given `product.template`.
        """
        if company_id:
            request.update_context(allowed_company_ids=[company_id])

        product_template = request.env['product.template'].browse(product_template_id)
        parent_combination = request.env['product.template.attribute.value'].browse(
            parent_combination + combination
        )

        return [
            dict(
                **self._get_product_information(
                    optional_product_template,
                    optional_product_template._get_first_possible_combination(
                        parent_combination=parent_combination
                    ),
                    currency_id,
                    parent_combination=parent_combination,
                ),
                parent_product_tmpl_ids=[product_template.id],
            )
            for optional_product_template in product_template.optional_product_ids
        ]

    @http.route('/crm_product_configurator/save_to_crm', type='json', auth='user', methods=['POST'])
    def save_to_crm(self, **kwargs):
        main_product = kwargs.get('main_product')
        optional_products = kwargs.get('optional_products', [])
        crm_lead_id = kwargs.get('crm_lead_id')

        _logger.info(f"[CRM Configurator] Received payload with lead_id={crm_lead_id}")

        if not crm_lead_id or not main_product:
            return {'error': 'Missing required data: crm_lead_id or main_product'}

        lead = request.env['crm.lead'].sudo().browse(int(crm_lead_id))
        if not lead.exists():
            return {'error': 'Lead not found'}

        def create_or_update_material_line(product_data, lead):
            try:
                # === Extract inputs from payload ===
                ptav_ids = list(map(int, product_data.get('ptav_ids', [])))
                template_id = int(product_data.get('product_template_id'))
                quantity = float(product_data.get('quantity', 1.0))
                product_id = product_data.get('product_id')
                custom_attribute_values = product_data.get('custom_attribute_values', [])
                m2o_values = product_data.get('m2o_values', [])

                # 🔥 CHECK FOR QUANTITY ATTRIBUTE
                # Iterate through custom values to find if any attribute is marked as 'is_quantity'
                for custom_val in custom_attribute_values:
                    ptav_id = custom_val.get('ptav_id')
                    custom_value = custom_val.get('custom_value')
                    
                    if ptav_id and custom_value:
                        ptav = request.env['product.template.attribute.value'].browse(int(ptav_id))
                        if ptav.attribute_id.is_quantity:
                            try:
                                quantity = float(custom_value)
                                _logger.info(f"✅ Quantity set from attribute '{ptav.attribute_id.name}': {quantity}")
                            except ValueError:
                                _logger.warning(f"⚠️ Invalid quantity value '{custom_value}' for attribute '{ptav.attribute_id.name}'")

                # 🔥 CHECK FOR QUANTITY UOM ATTRIBUTE
                # Find the "Quantity UOM" attribute value and map it to uom.uom
                quantity_uom_value = None
                for ptav_id in ptav_ids:
                    ptav = request.env['product.template.attribute.value'].browse(int(ptav_id))
                    if ptav.attribute_id.name == "Quantity UOM":
                        quantity_uom_value = ptav.name
                        _logger.info(f"✅ Found Quantity UOM attribute value: {quantity_uom_value}")
                        break
                
                # Search for matching UOM in uom.uom
                uom_to_set = None
                if quantity_uom_value:
                    matching_uom = request.env['uom.uom'].sudo().search([
                        ('name', '=', quantity_uom_value)
                    ], limit=1)
                    
                    if matching_uom:
                        uom_to_set = matching_uom.id
                        _logger.info(f"✅ Matched UOM '{quantity_uom_value}' to uom.uom ID: {uom_to_set}")
                    else:
                        _logger.warning(f"⚠️ No matching uom.uom found for '{quantity_uom_value}', UOM will be left blank")
                        uom_to_set = False

                # 🔥 FILE UPLOAD PAYLOAD (from frontend)
                file_upload_payload = product_data.get('file_upload', {}) or {}
                payload_file_name = file_upload_payload.get('file_name') or file_upload_payload.get('name')
                payload_file_data = file_upload_payload.get('file_data') or file_upload_payload.get('data')

                # NEW: CONDITIONAL FILE UPLOAD PAYLOAD (from frontend)
                conditional_file_payload = product_data.get('conditional_file_upload', {}) or {}
                conditional_file_name = conditional_file_payload.get('file_name') or conditional_file_payload.get('name')
                conditional_file_data = conditional_file_payload.get('file_data') or conditional_file_payload.get('data')

                if not product_id:
                    _logger.warning(
                        f"[CRM Configurator] Skipping: No product_id for template_id={template_id}"
                    )
                    return

                # Clean up blank lines
                request.env['crm.material.line'].sudo().search([
                    ('lead_id', '=', lead.id),
                    ('product_id', '=', False),
                ]).unlink()

                # Get product variant
                product_variant = request.env['product.product'].sudo().browse(int(product_id))
                if not product_variant.exists():
                    raise ValueError(f"Product ID {product_id} not found")

                if not product_variant.product_tmpl_id:
                    _logger.error(f"Product {product_id} has no template!")
                    return {'error': f'Product {product_id} is invalid (no template)'}

                template = product_variant.product_tmpl_id

                if template.id != template_id:
                    _logger.warning(
                        f"Template ID mismatch: expected {template_id}, got {template.id}"
                    )

                # UoM - Prioritize Quantity UOM attribute if found
                if uom_to_set is not None:
                    # Use the UOM from "Quantity UOM" attribute
                    uom_id = uom_to_set
                    if uom_id:
                        _logger.info(f"✅ Using UOM from Quantity UOM attribute: {uom_id}")
                    else:
                        _logger.info(f"⚠️ No matching UOM found for Quantity UOM attribute, leaving blank")
                else:
                    # Fall back to product's default UOM
                    uom_id = product_variant.uom_id.id if product_variant.uom_id else False
                    if not uom_id:
                        _logger.warning(f"Product {product_id} has no UOM, using default")
                        uom_rec = request.env.ref('uom.product_uom_unit', raise_if_not_found=False)
                        if uom_rec:
                            uom_id = uom_rec.id

                category_id = template.categ_id.id if template.categ_id else False

                # PTAV values of this variant
                attribute_values = product_variant.product_template_attribute_value_ids

                # ✅ Save M2O selections to PTAV records
                for m2o_val in m2o_values:
                    ptal_id = m2o_val.get('ptal_id')
                    res_id = m2o_val.get('res_id')
                    if ptal_id and res_id:
                        ptav_record = request.env['product.template.attribute.value'].sudo().search([
                            ('attribute_line_id', '=', ptal_id),
                            ('product_tmpl_id', '=', template.id),
                        ], limit=1)
                        if ptav_record:
                            ptav_record.write({'m2o_res_id': res_id})
                            _logger.info(
                                f"[CRM Configurator] M2O mapped: PTAV {ptav_record.id} "
                                f"ptal_id={ptal_id} → res_id={res_id}"
                            )

                # Re-read to get updated m2o_res_id values
                attribute_values = product_variant.product_template_attribute_value_ids

                # =========================
                # 🔥 FILE HANDLING - CRITICAL FIX
                # =========================
                attached_file_data = None
                attached_file_name = None
                
                # Priority 1: Frontend payload (preferred)
                if payload_file_data and payload_file_name:
                    attached_file_data = payload_file_data
                    attached_file_name = payload_file_name
                    _logger.info(f"📂 File from frontend payload: {payload_file_name}")
                else:
                    # Priority 2: PTAV fallback (legacy)
                    for av in attribute_values:
                        if av.attribute_id.display_type == "file_upload":
                            if av.file_data and av.file_name:
                                attached_file_data = av.file_data
                                attached_file_name = av.file_name
                                _logger.info(f"📂 File from PTAV fallback: {av.file_name}")
                            break

                # Check if template has file_upload attribute
                has_file_upload_ptav = any(
                    av.attribute_id.display_type == 'file_upload' for av in attribute_values
                )

                # Build description with proper gel-coat filtering
                attribute_lines = []
                last_skipped_was_gelcoat = False  # Track if we just skipped a gel-coat attribute
                last_was_product_name = False     # Track if we just processed Product Name
                last_was_gel_coat_req_no = False  # Track if last visible line was Gel Coat REQ: No
                
                # Helper to find custom value for a PTAL
                def get_custom_val(ptal):
                    for cv in custom_attribute_values:
                        if int(cv.get('ptav_id', 0)) in ptal.product_template_value_ids.ids:
                            return cv.get('custom_value')
                    return None

                # 🔥 Check if "Gel Coat REQ" is set to "No"
                gel_coat_required = True  # Default to True
                print(f"\n🔍 DEBUG: Total attribute_lines in template: {len(template.attribute_line_ids)}")
                print(f"🔍 DEBUG: Total attribute_values in variant: {len(attribute_values)}")
                for av in attribute_values:
                    print(f"   - {av.attribute_id.name}: {av.name} (is_gelcoat_flag: {av.attribute_id.is_gelcoat_required_flag})")
                
                for ptal in template.attribute_line_ids:
                    if ptal.attribute_id.name and "gel coat req" in ptal.attribute_id.name.lower():
                        selected_ptavs = attribute_values.filtered(lambda v: v.attribute_line_id == ptal)
                        for ptav in selected_ptavs:
                            if ptav.name and ptav.name.lower() == "no":
                                gel_coat_required = False
                                _logger.info("🔍 Gel Coat REQ is set to 'No', will hide Gel-coat attribute")
                                break
                        break

                for ptal in template.attribute_line_ids:
                    # Skip file upload
                    if ptal.attribute_id.display_type == "file_upload":
                        last_skipped_was_gelcoat = False
                        continue

                    # Skip is_quantity attributes
                    if ptal.attribute_id.is_quantity:
                        last_skipped_was_gelcoat = False
                        continue

                    # 🔥 Skip Gel-coat attribute if Gel Coat REQ is "No"
                    # BUT do NOT skip the "Gel Coat REQ" attribute itself!
                    attr_name_lower = ptal.attribute_id.name.lower() if ptal.attribute_id.name else ""
                    is_product_name = "product name" in attr_name_lower
                    
                    # 🔥 NEW: Skip paired attribute if previous was Product Name (e.g. skip "Units")
                    if ptal.attribute_id.pair_with_previous and last_was_product_name:
                        _logger.info(f"⏭️ Skipping paired attribute '{ptal.attribute_id.name}' because previous was Product Name")
                        last_was_product_name = False
                        continue

                    # 🔥 NEW: Skip paired attribute if previous was Gel Coat REQ: No (e.g. skip "Kg / Unit")
                    if ptal.attribute_id.pair_with_previous and last_was_gel_coat_req_no:
                        _logger.info(f"⏭️ Skipping paired attribute '{ptal.attribute_id.name}' because previous was Gel Coat REQ: No")
                        # Keep last_was_gel_coat_req_no = True in case there are more paired attributes
                        continue

                    is_gel_coat_req_attr = "gel coat req" in attr_name_lower or "gelcoat req" in attr_name_lower
                    
                    # Check if this is a gel-coat related attribute (but not the "Gel Coat REQ" itself)
                    is_gelcoat_attr = (
                        ptal.attribute_id.is_gelcoat_required_flag or 
                        ("gel" in attr_name_lower and "coat" in attr_name_lower and "req" not in attr_name_lower)
                    )
                    
                    # 🔥 NEW: Also skip if this attribute has pair_with_previous and the last attribute was a skipped gel-coat
                    if ptal.attribute_id.pair_with_previous and last_skipped_was_gelcoat:
                        _logger.info(f"⏭️ Skipping paired attribute '{ptal.attribute_id.name}' because previous gel-coat was skipped")
                        last_skipped_was_gelcoat = False  # Reset for next iteration
                        last_was_product_name = False
                        continue
                    
                    if not gel_coat_required and is_gelcoat_attr and not is_gel_coat_req_attr:
                        _logger.info(f"⏭️ Skipping Gel-coat attribute '{ptal.attribute_id.name}' because Gel Coat REQ is No")
                        last_skipped_was_gelcoat = True  # Mark that we skipped a gel-coat attribute
                        last_was_product_name = False
                        continue
                    
                    # Reset the flag if we're processing a non-gel-coat attribute
                    last_skipped_was_gelcoat = False

                    # Find selected PTAVs for this line
                    selected_ptavs = attribute_values.filtered(lambda v: v.attribute_line_id == ptal)
                    
                    _logger.info(f"🔍 Processing attribute '{ptal.attribute_id.name}': found {len(selected_ptavs)} selected values")
                    
                    if not selected_ptavs:
                        _logger.info(f"⚠️ No selected values for '{ptal.attribute_id.name}', skipping")
                        continue

                    # Get display values
                    display_values = []
                    for ptav in selected_ptavs:
                        val = ""
                        if ptav.is_custom:
                            val = get_custom_val(ptal) # No fallback to name
                        elif ptal.attribute_id.display_type == "m2o" and ptav.m2o_res_id:
                             rec = request.env[ptal.attribute_id.m2o_model_id.model].sudo().browse(ptav.m2o_res_id)
                             val = rec.display_name
                        else:
                            val = ptav.name
                        display_values.append(val)
                        _logger.info(f"  📝 Value for '{ptal.attribute_id.name}': {val}")
                    
                    # Filter out empty or '0' values
                    display_values = [v for v in display_values if v and v != '0']
                    
                    if not display_values:
                        _logger.info(f"⚠️ All values filtered out for '{ptal.attribute_id.name}', skipping")
                        continue

                    value_str = ", ".join(display_values)
                    _logger.info(f"✅ Adding to description: '{ptal.attribute_id.name}: {value_str}'")

                    # Handle Pair with Previous
                    if ptal.attribute_id.pair_with_previous and attribute_lines:
                        # Append to last line
                        attribute_lines[-1] += f" {value_str}"
                    else:
                        # New line
                        attribute_lines.append(f"• {ptal.attribute_id.name}: {value_str}")
                    
                    # Update tracking flags
                    last_was_product_name = is_product_name
                    
                    # Update last_was_gel_coat_req_no
                    if ptal.attribute_id.pair_with_previous and attribute_lines:
                        # Appended to existing line. Flag state remains unchanged (effectively False because we skipped if True)
                        pass
                    else:
                        # New line
                        if is_gel_coat_req_attr and "no" in value_str.lower():
                            last_was_gel_coat_req_no = True
                        else:
                            last_was_gel_coat_req_no = False


                attribute_description = "\n".join(attribute_lines) if attribute_lines else ""
                print("\n" + "="*80)
                print(f"📋 ATTRIBUTE DESCRIPTION DEBUG:")
                print(f"   Total attributes: {len(attribute_lines)}")
                print(f"   Gel coat required: {gel_coat_required}")
                print(f"   Description:\n{attribute_description}")
                print("="*80 + "\n")
                _logger.info(f"📋 Final attribute_description:\n{attribute_description}")
                _logger.info(f"📋 Total attributes in description: {len(attribute_lines)}")

                # =========================
                # BUILD DISPLAY NAME
                # =========================
                if product_variant.default_code:
                    base_name = f"[{product_variant.default_code}] {product_variant.name}"
                else:
                    base_name = product_variant.name

                # Attributes summary for display name (SKIP file_upload, is_quantity, gel-coat if not required)
                attributes_summary_parts = []
                for attr_value in attribute_values:
                    if attr_value.attribute_id.display_type == "file_upload":
                        continue
                    if attr_value.attribute_id.is_quantity:
                        continue
                    
                    # 🔥 Skip gel-coat attributes if Gel Coat REQ is "No"
                    attr_name_lower = attr_value.attribute_id.name.lower() if attr_value.attribute_id.name else ""
                    is_gel_coat_req_attr = "gel coat req" in attr_name_lower or "gelcoat req" in attr_name_lower
                    is_gelcoat_attr = (
                        attr_value.attribute_id.is_gelcoat_required_flag or 
                        ("gel" in attr_name_lower and "coat" in attr_name_lower and "req" not in attr_name_lower)
                    )
                    if not gel_coat_required and is_gelcoat_attr and not is_gel_coat_req_attr:
                        continue
                    
                    if not attr_value.is_custom:
                        if attr_value.attribute_id.display_type == "m2o":
                            if attr_value.m2o_res_id:
                                rec = request.env[
                                    attr_value.attribute_id.m2o_model_id.model
                                ].sudo().browse(attr_value.m2o_res_id)
                                attributes_summary_parts.append(rec.display_name)
                            else:
                                attributes_summary_parts.append(attr_value.name)
                        else:
                            attributes_summary_parts.append(attr_value.name)

                for custom_val in custom_attribute_values:
                    if custom_val.get('custom_value'):
                        attributes_summary_parts.append(custom_val['custom_value'])

                attributes_summary = ", ".join(attributes_summary_parts)
                product_display_name = (
                    f"{base_name} ({attributes_summary})"
                    if attributes_summary
                    else base_name
                )

                # =========================
                # BUILD ATTRIBUTE SUMMARY (Reuse logic)
                # =========================
                # Strip "• " from lines to get "Name: Value" format
                attribute_summary_parts = [line.replace("• ", "", 1) for line in attribute_lines]
                attribute_summary = ", ".join(attribute_summary_parts)

                # =========================
                # FULL DESCRIPTION
                # =========================
                base_description = (
                    product_variant.description_sale or template.description_sale or ""
                )
                if attribute_description:
                    if base_description:
                        full_description = (
                            f"{base_description}\n\n📋 Selected Attributes:\n"
                            f"{attribute_description}"
                        )
                    else:
                        full_description = (
                            f"📋 Selected Attributes:\n{attribute_description}"
                        )
                else:
                    full_description = base_description

                # =========================
                # EXISTING LINE CHECK - REMOVED
                # =========================
                # Always create a new line when user explicitly adds from configurator
                # This allows adding the same product multiple times
                existing_line = False

                # =========================
                # PREPARE LINE VALUES
                # =========================
                line_vals = {
                    'product_id': product_variant.id,
                    'quantity': quantity if quantity > 0 else 1.0,
                    'product_template_id': template.id,
                    'product_template_attribute_value_ids': [(6, 0, ptav_ids)],
                }

                # 🔥 CRITICAL: SAVE FILE TO LINE
                if attached_file_data and attached_file_name:
                    try:
                        # Remove data URI prefix if present (e.g., "data:image/png;base64,")
                        if ',' in attached_file_data:
                            attached_file_data = attached_file_data.split(',')[1]
                        
                        # ✅ Save base64 string directly to Binary field
                        line_vals['attached_file_id'] = attached_file_data
                        line_vals['attached_file_name'] = attached_file_name

                        _logger.info(
                            f"✅ File will be saved to line:\n"
                            f"    ➤ Name: {attached_file_name}\n"
                            f"    ➤ Size: {len(attached_file_data)} chars (base64)"
                        )
                    except Exception as e:
                        _logger.error(f"❌ File processing failed: {e}")
                        _logger.exception("Full traceback:")
                else:
                    _logger.info("⚠️ No file_upload payload received")

                # NEW: SAVE CONDITIONAL FILE TO LINE
                if conditional_file_data and conditional_file_name:
                    try:
                        # Remove data URI prefix if present
                        if ',' in conditional_file_data:
                            conditional_file_data = conditional_file_data.split(',')[1]
                        
                        # Save to conditional file fields
                        line_vals['boq_attachment_id'] = conditional_file_data
                        line_vals['boq_attachment_name'] = conditional_file_name

                        _logger.info(
                            f"✅ Conditional file will be saved to line:\n"
                            f"    ➤ Name: {conditional_file_name}\n"
                            f"    ➤ Size: {len(conditional_file_data)} chars (base64)"
                        )
                    except Exception as e:
                        _logger.error(f"❌ Conditional file processing failed: {e}")
                        _logger.exception("Full traceback:")
                else:
                    _logger.info("⚠️ No conditional_file_upload payload received")

                # Optional fields
                if uom_id:
                    line_vals['product_uom_id'] = uom_id
                if category_id:
                    line_vals['product_category_id'] = category_id
                if product_display_name:
                    line_vals['product_display_name'] = product_display_name
                if attribute_summary:
                    line_vals['attribute_summary'] = attribute_summary
                if full_description:
                    line_vals['description'] = full_description
                
                # Set default price from product
                if product_variant:
                    line_vals['price'] = product_variant.lst_price

                # Custom attribute values
                if custom_attribute_values:
                    custom_vals_commands = []
                    for custom_val in custom_attribute_values:
                        ptav_id = custom_val.get('ptav_id')
                        custom_value = custom_val.get('custom_value', '')
                        if ptav_id and custom_value:
                            custom_vals_commands.append((
                                0, 0, {
                                    'custom_product_template_attribute_value_id': int(ptav_id),
                                    'custom_value': custom_value,
                                }
                            ))

                    if custom_vals_commands:
                        line_vals['product_custom_attribute_value_ids'] = custom_vals_commands

                # =========================
                # CREATE OR UPDATE LINE
                # =========================
                if existing_line:
                    _logger.info(
                        f"[CRM Configurator] Updating line {existing_line.id}: "
                        f"{product_display_name}"
                    )
                    existing_line.write(line_vals)
                else:
                    _logger.info(
                        f"[CRM Configurator] Creating new line: {product_display_name}"
                    )
                    # Try to update last blank line first
                    last_line = request.env['crm.material.line'].sudo().search([
                        ('lead_id', '=', lead.id),
                        ('product_id', '=', False),
                    ], order='id desc', limit=1)
                    
                    if last_line:
                        last_line.write(line_vals)
                        _logger.info(
                            f"[CRM Configurator] Updated blank line {last_line.id}\n"
                            f"    ➤ File: {last_line.attached_file_name or 'None'}\n"
                            f"    ➤ File saved: {'Yes' if last_line.attached_file_id else 'No'}"
                        )
                    else:
                        line_vals['lead_id'] = lead.id
                        new_line = request.env['crm.material.line'].sudo().create(line_vals)
                        _logger.info(
                            f"[CRM Configurator] Created line {new_line.id}\n"
                            f"    ➤ File: {new_line.attached_file_name or 'None'}\n"
                            f"    ➤ File saved: {'Yes' if new_line.attached_file_id else 'No'}"
                        )

            except Exception as e:
                _logger.error(
                    f"[CRM Configurator] Error: {repr(e)}\n{traceback.format_exc()}"
                )
                raise


        # Retry logic for concurrent update errors
        max_retries = 3
        retry_delay = 0.2  # Start with 200ms delay
        last_error = None
        
        for attempt in range(max_retries):
            try:
                create_or_update_material_line(main_product, lead)
                for opt in optional_products:
                    create_or_update_material_line(opt, lead)

                request.env.cr.commit()
                return {'success': True}
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                
                # Check if it's a concurrent update error and we have retries left
                if "concurrent update" in error_msg and attempt < max_retries - 1:
                    _logger.warning(
                        f"[CRM Configurator] Concurrent update error on attempt {attempt + 1}/{max_retries}, "
                        f"retrying in {retry_delay}s..."
                    )
                    request.env.cr.rollback()
                    import time
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    # Last attempt or different error
                    _logger.error(f"[CRM Configurator] Fatal error after {attempt + 1} attempts: {repr(e)}")
                    request.env.cr.rollback()
                    return {'success': False, 'error': str(e)}
        
        # Should not reach here, but just in case
        _logger.error(f"[CRM Configurator] All retries exhausted: {repr(last_error)}")
        return {'success': False, 'error': str(last_error)}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _get_product_information(
        self,
        product_template,
        combination,
        currency_id,
        quantity=1,
        product_uom_id=None,
        parent_combination=None,
    ):
        product_uom = request.env['uom.uom'].browse(product_uom_id)
        currency = request.env['res.currency'].browse(currency_id)
        product = product_template._get_variant_for_combination(combination)

        attribute_exclusions = product_template._get_attribute_exclusions(
            parent_combination=parent_combination,
            combination_ids=combination.ids,
        )

        return dict(
            product_tmpl_id=product_template.id,
            **self._get_basic_product_information(
                product or product_template,
                combination,
                quantity=quantity,
                uom=product_uom,
                currency=currency,
            ),
            quantity=quantity,
            attribute_lines=[
                dict(
                    id=ptal.id,
                    # ATTRIBUTE meta (with m2o model info and pair_with_previous)
                    attribute=dict(
                        **ptal.attribute_id.read(
                            ['id', 'name', 'display_type', 'm2o_model_id', 'pair_with_previous', 'is_width_check', 'is_quantity', 'is_gelcoat_required_flag']
                        )[0],
                        m2o_values=(
                            [
                                dict(id=rec.id, name=rec.display_name)
                                for rec in request.env[
                                    ptal.attribute_id.m2o_model_id.model
                                ]
                                .sudo()
                                .search([], order="name asc")
                            ]
                            if (
                                ptal.attribute_id.display_type == "m2o"
                                and ptal.attribute_id.m2o_model_id
                                and ptal.attribute_id.m2o_model_id.model
                            )
                            else []
                        ),
                    ),
                    # PTAV list (expose m2o_res_id to FE as well)
                    attribute_values=[
                        dict(
                            **ptav.read(
                                ['name', 'html_color', 'image', 'is_custom', 'm2o_res_id', 'required_file']
                            )[0]
                        )
                        for ptav in ptal.product_template_value_ids
                        if ptav.ptav_active
                        or (combination and ptav.id in combination.ids)
                    ],
                    selected_attribute_value_ids=combination.filtered(
                        lambda c: ptal in c.attribute_line_id
                    ).ids,
                    create_variant=ptal.attribute_id.create_variant,
                )
                for ptal in product_template.attribute_line_ids
            ],
            exclusions=attribute_exclusions['exclusions'],
            archived_combinations=attribute_exclusions['archived_combinations'],
            parent_exclusions=attribute_exclusions['parent_exclusions'],
        )

    def _get_basic_product_information(self, product_or_template, combination, **kwargs):
        """ Return basic information about a product
        """
        basic_information = dict(
            **product_or_template.read(['description_sale', 'display_name'])[0]
        )
        # If the product is a template, adapt name using combination
        if not product_or_template.is_product_variant:
            basic_information['id'] = False
            combination_name = combination._get_combination_name()
            if combination_name:
                basic_information.update(
                    display_name=f"{basic_information['display_name']} ({combination_name})"
                )
        return dict(
            **basic_information,
            price=product_or_template.standard_price,
        )