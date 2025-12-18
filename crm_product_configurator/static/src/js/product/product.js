/** @odoo-module */

import { Component } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import {
    ProductTemplateAttributeLine as PTAL
} from "../product_template_attribute_line/product_template_attribute_line";

export class Product extends Component {
    static components = { PTAL };
    static template = "crm_product_configurator.product";
    static props = {
        id: { type: [Number, { value: false }], optional: true },
        product_tmpl_id: Number,
        display_name: String,
        description_sale: [Boolean, String], // backend sends 'false' when there is no description
        price: { type: [Number, { value: false }], optional: true },
        quantity: Number,
        attribute_lines: Object,
        optional: Boolean,
        imageURL: { type: String, optional: true },
        archived_combinations: Array,
        exclusions: Object,
        parent_exclusions: Object,
        parent_product_tmpl_ids: { type: Array, element: Number, optional: true },
    };

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Increase the quantity of the product in the state.
     */
    increaseQuantity() {
        this.env.setQuantity(this.props.product_tmpl_id, this.props.quantity + 1);
    }

    /**
     * Set the quantity of the product in the state.
     *
     * @param {Event} event
     */
    setQuantity(event) {
        const newQty = parseFloat(event.target.value);
        this.env.setQuantity(this.props.product_tmpl_id, newQty);
    }

    /**
     * Decrease the quantity of the product in the state.
     */
    decreaseQuantity() {
        this.env.setQuantity(this.props.product_tmpl_id, this.props.quantity - 1);
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Return the price, in the format of the given currency.
     *
     * @return {String} - The price, in the format of the given currency.
     */
    getFormattedPrice() {
        return formatCurrency(this.props.price, this.env.currencyId);
    }
    isVisible(ptal) {
        // 1. Check if current attribute is "Gel-coat"
        if (ptal.attribute.name === "Gel-coat") {
            // 2. Find attribute with is_gelcoat_required_flag = True
            // Note: attribute_lines is an Object (or Array depending on context, but props definition says Object, 
            // usually it's an array in Odoo 16+, let's check usage in template: t-foreach="this.props.attribute_lines" t-as="ptal"
            // So it is iterable. If it's an object/array, Object.values handles both usually if keys are indices, 
            // but let's assume array if t-foreach works directly. 
            // However, props definition says Object. Let's be safe and use Object.values if it's not an array.
            const lines = Array.isArray(this.props.attribute_lines) ? this.props.attribute_lines : Object.values(this.props.attribute_lines);

            const requiredAttr = lines.find(
                l => l.attribute.is_gelcoat_required_flag
            );

            if (requiredAttr) {
                // 3. Check selected value
                const selectedId = requiredAttr.selected_attribute_value_ids[0];
                if (selectedId) {
                    const selectedValue = requiredAttr.attribute_values.find(v => v.id === selectedId);
                    // Check for "yes" (case-insensitive)
                    if (selectedValue && selectedValue.name.toLowerCase() === "yes") {
                        return true;
                    }
                }
                return false; // Hide if "Yes" is not selected
            }
        }
        return true; // Show all other attributes
    }
}
