/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState, useSubEnv, useEffect } from "@odoo/owl";
import { Dialog } from '@web/core/dialog/dialog';
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { CrmProductList } from "../product_list/product_list";
import { rpc } from "@web/core/network/rpc";

export class crmProductConfiguratorDialog extends Component {
    static components = { Dialog, CrmProductList };
    static template = 'crm_product_configurator.dialog';
    static props = {
        productTemplateId: Number,
        ptavIds: { type: Array, element: Number },
        customAttributeValues: {
            type: Array,
            element: Object,
            shape: {
                ptavId: Number,
                value: String,
            }
        },
        quantity: Number,
        productUOMId: { type: Number, optional: true },
        companyId: { type: Number, optional: true },
        currencyId: { type: Number, optional: true },
        crmLeadId: Number,
        edit: { type: Boolean, optional: true },
        save: Function,
        discard: Function,
        close: Function,
    };

    static defaultProps = {
        edit: false,
    }

    setup() {
        this.optionalProductsTitle = _t("Add optional products");
        this.title = _t("Configure your product");
        this.rpc = rpc;
        this.state = useState({
            products: [],
            optionalProducts: [],
            fileUploads: {}, // 🔥 NEW: Store file uploads per product
            m2oValues: {},   // 🔥 NEW: Store M2O selections per product
            conditionalFileUploads: {}, // NEW: Store conditional file uploads per product
        });

        useSubEnv({
            mainProductTmplId: this.props.productTemplateId,
            currencyId: this.props.currencyId,
            addProduct: this._addProduct.bind(this),
            removeProduct: this._removeProduct.bind(this),
            setQuantity: this._setQuantity.bind(this),
            updateProductTemplateSelectedPTAV: this._updateProductTemplateSelectedPTAV.bind(this),
            updatePTAVCustomValue: this._updatePTAVCustomValue.bind(this),
            updateFileUpload: this._updateFileUpload.bind(this),        // 🔥 NEW
            updateM2OValue: this._updateM2OValue.bind(this),            // 🔥 NEW
            updateConditionalFileUpload: this._updateConditionalFileUpload.bind(this), // NEW
            isPossibleCombination: this._isPossibleCombination,
            // ⭐ NEW: expose callback for auto-fill width
            autoFillWidthFromM2O: this.autoFillWidthFromM2O.bind(this),
        });

        useEffect(() => { }, () => [this.state.products]);

        onWillStart(async () => {
            const { products, optional_products } = await this._loadData(this.props.edit);
            this.state.products = products;
            this.state.optionalProducts = optional_products;
            this._setDefaultThickness();

            for (const customValue of this.props.customAttributeValues) {
                this._updatePTAVCustomValue(
                    this.env.mainProductTmplId,
                    customValue.ptavId,
                    customValue.value
                );
            }

            if (this.state.products.length > 0) {
                this._checkExclusions(this.state.products[0]);
            }

            // 🔥 NEW: Fetch is_width_check, pair_with_previous manually since backend might not send it
            await this._enrichAttributesWithWidthCheck();
        });
    }

    // 🔥 NEW: Helper to fetch is_width_check, pair_with_previous AND m2o_model_technical_name
    async _enrichAttributesWithWidthCheck() {
        const allProducts = [...this.state.products, ...this.state.optionalProducts];
        const attributeIds = new Set();

        for (const product of allProducts) {
            for (const ptal of product.attribute_lines || []) {
                if (ptal.attribute && ptal.attribute.id) {
                    attributeIds.add(ptal.attribute.id);
                }
            }
        }

        if (attributeIds.size === 0) return;

        try {
            // Fetch is_width_check, pair_with_previous AND m2o_model_id
            const attributesData = await this.rpc("/web/dataset/call_kw/product.attribute/read", {
                model: "product.attribute",
                method: "read",
                args: [[...attributeIds], ["is_width_check", "m2o_model_id", "pair_with_previous", "is_quantity", "is_gelcoat_required_flag"]],
                kwargs: {},
            });

            // Collect ir.model IDs
            const irModelIds = new Set();
            const attrToIrModelId = {};

            for (const attr of attributesData) {
                if (attr.m2o_model_id) {
                    // m2o_model_id is [id, name]
                    const irModelId = Array.isArray(attr.m2o_model_id) ? attr.m2o_model_id[0] : attr.m2o_model_id;
                    if (irModelId) {
                        irModelIds.add(irModelId);
                        attrToIrModelId[attr.id] = irModelId;
                    }
                }
            }

            // Fetch model names from ir.model
            const irModelMap = {};
            if (irModelIds.size > 0) {
                const irModelsData = await this.rpc("/web/dataset/call_kw/ir.model/read", {
                    model: "ir.model",
                    method: "read",
                    args: [[...irModelIds], ["model"]],
                    kwargs: {},
                });
                for (const m of irModelsData) {
                    irModelMap[m.id] = m.model;
                }
            }

            const attributeMap = {};
            for (const attr of attributesData) {
                attributeMap[attr.id] = {
                    is_width_check: attr.is_width_check,
                    m2o_model_technical_name: attrToIrModelId[attr.id] ? irModelMap[attrToIrModelId[attr.id]] : false,
                    pair_with_previous: attr.pair_with_previous, // 🔥 NEW
                    is_quantity: attr.is_quantity, // 🔥 NEW
                    is_gelcoat_required_flag: attr.is_gelcoat_required_flag, // 🔥 NEW
                };
            }

            // Update state
            for (const product of allProducts) {
                for (const ptal of product.attribute_lines || []) {
                    if (ptal.attribute && attributeMap[ptal.attribute.id]) {
                        ptal.attribute.is_width_check = attributeMap[ptal.attribute.id].is_width_check;
                        ptal.attribute.m2o_model_technical_name = attributeMap[ptal.attribute.id].m2o_model_technical_name;
                        ptal.attribute.pair_with_previous = attributeMap[ptal.attribute.id].pair_with_previous; // 🔥 NEW
                        ptal.attribute.is_quantity = attributeMap[ptal.attribute.id].is_quantity; // 🔥 NEW
                        ptal.attribute.is_gelcoat_required_flag = attributeMap[ptal.attribute.id].is_gelcoat_required_flag; // 🔥 NEW
                    }
                }
            }
            console.log("✅ Enriched attributes:", attributeMap);
        } catch (err) {
            console.error("❌ Failed to fetch attribute details:", err);
        }
    }

    autoFillWidthFromM2O(productTmplId, widthValue) {
        const product = this.state.products.find(p => p.product_tmpl_id === productTmplId);
        if (!product) return;

        const widthPTAL = product.attribute_lines.find(ptal =>
            ptal.attribute.name.toLowerCase() === "width"
        );
        if (!widthPTAL) return;

        const customPTAV = widthPTAL.attribute_values.find(v => v.is_custom);
        if (customPTAV) {
            widthPTAL.selected_attribute_value_ids = [customPTAV.id];
        }

        widthPTAL.customValue = widthValue;

        // 🔥 UI Refresh
        this.state.products = [...this.state.products];
    }

    // 🔥 NEW: Store file upload in state
    _updateFileUpload(productTmplId, ptalId, filePayload) {
        const key = `${productTmplId}_${ptalId}`;

        // If deleted (filePayload = null)
        if (!filePayload) {
            delete this.state.fileUploads[key];
            console.log(`🗑 File removed for ${key}`);
            return;
        }

        // If new or replaced file
        this.state.fileUploads[key] = filePayload;
        console.log(`📎 File stored for ${key}: ${filePayload.file_name}`);
    }


    // 🔥 NEW: Store M2O value in state
    _updateM2OValue(productTmplId, ptalId, resId) {
        const key = `${productTmplId}_${ptalId}`;
        this.state.m2oValues[key] = resId;

        const product = this._findProduct(productTmplId);
        if (!product) return;

        const ptal = product.attribute_lines.find(l => l.id === ptalId);
        if (!ptal) return;

        const selectedPtav = ptal.attribute_values.find(v => ptal.selected_attribute_value_ids.includes(v.id));
        if (!selectedPtav) return;

        // 🔥 CRITICAL: set m2o_res_id so UI shows selected value
        selectedPtav.m2o_res_id = resId;
    }


    // 🔥 NEW: Retrieve file for product
    _getFileUploadForProduct(productTmplId) {
        for (const key in this.state.fileUploads) {
            const [tmplId, ptalId] = key.split("_").map(Number);
            if (tmplId === Number(productTmplId)) {           // 🔥 correct match
                return this.state.fileUploads[key];
            }
        }
        return null;
    }


    // 🔥 NEW: Retrieve M2O values for product
    _getM2OValuesForProduct(productTmplId) {
        const m2oValues = [];
        for (const key in this.state.m2oValues) {
            if (key.startsWith(`${productTmplId}_`)) {
                const ptalId = parseInt(key.split('_')[1]);
                m2oValues.push({
                    ptal_id: ptalId,
                    res_id: this.state.m2oValues[key]
                });
            }
        }
        return m2oValues;
    }

    // NEW: Store conditional file upload in state
    _updateConditionalFileUpload(productTmplId, ptalId, filePayload) {
        const key = `${productTmplId}_${ptalId}`;

        // If deleted (filePayload = null)
        if (!filePayload) {
            delete this.state.conditionalFileUploads[key];
            console.log(`🗑 Conditional file removed for ${key}`);
            return;
        }

        // If new or replaced file
        this.state.conditionalFileUploads[key] = filePayload;
        console.log(`📎 Conditional file stored for ${key}: ${filePayload.file_name}`);
    }

    // NEW: Retrieve conditional file for product
    _getConditionalFileUploadForProduct(productTmplId) {
        for (const key in this.state.conditionalFileUploads) {
            const [tmplId, ptalId] = key.split("_").map(Number);
            if (tmplId === Number(productTmplId)) {
                return this.state.conditionalFileUploads[key];
            }
        }
        return null;
    }

    _setDefaultThickness() {
        const mainProduct = this.state.products[0];
        if (!mainProduct) return;

        const thicknessAttributeLine = mainProduct.attribute_lines.find(
            ptal => ptal.attribute.name.toLowerCase() === 'thickness'
        );

        if (thicknessAttributeLine && thicknessAttributeLine.selected_attribute_value_ids.length === 0) {
            const defaultThicknessValue = thicknessAttributeLine.attribute_values.find(
                ptav => ptav.name === '5-7'
            );

            if (defaultThicknessValue) {
                this._updateProductTemplateSelectedPTAV(
                    mainProduct.product_tmpl_id,
                    thicknessAttributeLine.id,
                    defaultThicknessValue.id,
                    false
                );
            }
        }
    }

    async _loadData(onlyMainProduct) {
        const params = {
            product_template_id: this.props.productTemplateId,
            currency_id: this.props.currencyId,
            quantity: this.props.quantity,
            product_uom_id: this.props.productUOMId,
            company_id: this.props.companyId,
            ptav_ids: this.props.ptavIds,
            only_main_product: onlyMainProduct,
        };
        return await this.rpc('/crm_product_configurator/get_values', params);
    }

    async _createProduct(product) {
        return this.rpc('/crm_product_configurator/create_product', {
            product_template_id: product.product_tmpl_id,
            combination: this._getCombination(product),
        });
    }

    async _updateCombination(product, quantity) {
        return this.rpc('/crm_product_configurator/update_combination', {
            product_template_id: product.product_tmpl_id,
            combination: this._getCombination(product),
            currency_id: this.props.currencyId,
            so_date: this.props.soDate,
            quantity: quantity || 0.0,
            product_uom_id: this.props.productUOMId,
            company_id: this.props.companyId,
            pricelist_id: this.props.pricelistId,
        });
    }

    async _getOptionalProducts(product) {
        return this.rpc('/crm_product_configurator/get_optional_products', {
            product_template_id: product.product_tmpl_id,
            combination: this._getCombination(product),
            parent_combination: this._getParentsCombination(product),
            currency_id: this.props.currencyId,
            so_date: this.props.soDate,
            company_id: this.props.companyId,
            pricelist_id: this.props.pricelistId,
        });
    }

    async _addProduct(productTmplId) {
        const index = this.state.optionalProducts.findIndex(
            p => p.product_tmpl_id === productTmplId
        );
        if (index >= 0) {
            this.state.products.push(...this.state.optionalProducts.splice(index, 1));
            const product = this._findProduct(productTmplId);
            let newOptionalProducts = await this._getOptionalProducts(product);
            for (const newOptionalProductDict of newOptionalProducts) {
                const newProduct = this._findProduct(newOptionalProductDict.product_tmpl_id);
                if (newProduct) {
                    newOptionalProducts = newOptionalProducts.filter(
                        (p) => p.product_tmpl_id != newOptionalProductDict.product_tmpl_id
                    );
                    newProduct.parent_product_tmpl_ids.push(productTmplId);
                }
            }
            if (newOptionalProducts) this.state.optionalProducts.push(...newOptionalProducts);
        }
    }

    _removeProduct(productTmplId) {
        const index = this.state.products.findIndex(p => p.product_tmpl_id === productTmplId);
        if (index >= 0) {
            this.state.optionalProducts.push(...this.state.products.splice(index, 1));
            for (const childProduct of this._getChildProducts(productTmplId)) {
                childProduct.parent_product_tmpl_ids = childProduct.parent_product_tmpl_ids.filter(
                    id => id !== productTmplId
                );
                if (!childProduct.parent_product_tmpl_ids.length) {
                    this._removeProduct(childProduct.product_tmpl_id);
                    this.state.optionalProducts.splice(
                        this.state.optionalProducts.findIndex(
                            p => p.product_tmpl_id === childProduct.product_tmpl_id
                        ), 1
                    );
                }
            }
        }
    }

    async _setQuantity(productTmplId, quantity) {
        if (quantity <= 0) {
            if (productTmplId === this.env.mainProductTmplId) {
                const product = this._findProduct(productTmplId);
                const { price } = await this._updateCombination(product, 1);
                product.quantity = 1;
                product.price = parseFloat(price);
                return;
            }
            this._removeProduct(productTmplId);
        } else {
            const product = this._findProduct(productTmplId);
            const { price } = await this._updateCombination(product, quantity);
            product.quantity = quantity;
            product.price = parseFloat(price);
        }
    }

    async _updateProductTemplateSelectedPTAV(productTmplId, ptalId, ptavId, multiIdsAllowed) {
        const product = this._findProduct(productTmplId);
        let selectedIds = product.attribute_lines.find(ptal => ptal.id === ptalId).selected_attribute_value_ids;
        if (multiIdsAllowed) {
            const ptavID = parseInt(ptavId);
            if (!selectedIds.includes(ptavID)) {
                selectedIds.push(ptavID);
            } else {
                selectedIds = selectedIds.filter(ptav => ptav !== ptavID);
            }
        } else {
            selectedIds = [parseInt(ptavId)];
        }
        product.attribute_lines.find(ptal => ptal.id === ptalId).selected_attribute_value_ids = selectedIds;
        this._checkExclusions(product);
        if (this._isPossibleCombination(product)) {
            const updatedValues = await this._updateCombination(product, product.quantity);
            Object.assign(product, updatedValues);
            if (!product.id && product.attribute_lines.every(ptal => ptal.create_variant === "always")) {
                const combination = this._getCombination(product);
                product.archived_combinations = product.archived_combinations.concat([combination]);
                this._checkExclusions(product);
            }
        }
    }

    _updatePTAVCustomValue(productTmplId, ptavId, customValue) {
        const product = this._findProduct(productTmplId);
        const ptal = product.attribute_lines.find(
            ptal => ptal.selected_attribute_value_ids.includes(ptavId)
        );
        if (ptal) {
            ptal.customValue = customValue;
        }
    }

    _checkExclusions(product, checked = undefined) {
        const combination = this._getCombination(product);
        const exclusions = product.exclusions;
        const parentExclusions = product.parent_exclusions;
        const archivedCombinations = product.archived_combinations;
        const parentCombination = this._getParentsCombination(product);
        const childProducts = this._getChildProducts(product.product_tmpl_id);
        const ptavList = product.attribute_lines.flat().flatMap(ptal => ptal.attribute_values);
        ptavList.map(ptav => ptav.excluded = false);

        if (exclusions) {
            for (const ptavId of combination) {
                for (const excludedPtavId of exclusions[ptavId]) {
                    ptavList.find(ptav => ptav.id === excludedPtavId).excluded = true;
                }
            }
        }

        if (parentCombination) {
            for (const ptavId of parentCombination) {
                for (const excludedPtavId of (parentExclusions[ptavId] || [])) {
                    ptavList.find(ptav => ptav.id === excludedPtavId).excluded = true;
                }
            }
        }

        if (archivedCombinations) {
            for (const excludedCombination of archivedCombinations) {
                const ptavCommon = excludedCombination.filter((ptav) => combination.includes(ptav));
                if (ptavCommon.length === combination.length) {
                    for (const excludedPtavId of ptavCommon) {
                        ptavList.find(ptav => ptav.id === excludedPtavId).excluded = true;
                    }
                } else if (ptavCommon.length === (combination.length - 1)) {
                    const disabledPtavId = excludedCombination.find(
                        (ptav) => !combination.includes(ptav)
                    );
                    const excludedPtav = ptavList.find(ptav => ptav.id === disabledPtavId);
                    if (excludedPtav) {
                        excludedPtav.excluded = true;
                    }
                }
            }
        }

        const checkedProducts = checked || [];
        for (const optionalProductTmpl of childProducts) {
            if (!checkedProducts.includes(optionalProductTmpl)) {
                checkedProducts.push(optionalProductTmpl);
                this._checkExclusions(optionalProductTmpl, checkedProducts);
            }
        }
    }

    _findProduct(productTmplId) {
        return this.state.products.find(p => p.product_tmpl_id === productTmplId) ||
            this.state.optionalProducts.find(p => p.product_tmpl_id === productTmplId);
    }

    _getChildProducts(productTmplId) {
        return [
            ...this.state.products.filter(p => p.parent_product_tmpl_ids?.includes(productTmplId)),
            ...this.state.optionalProducts.filter(p => p.parent_product_tmpl_ids?.includes(productTmplId))
        ];
    }

    _getCombination(product) {
        return product.attribute_lines.flatMap(ptal => ptal.selected_attribute_value_ids);
    }

    _getParentsCombination(product) {
        let parentsCombination = [];
        for (const parentProductTmplId of product.parent_product_tmpl_ids || []) {
            parentsCombination.push(this._getCombination(this._findProduct(parentProductTmplId)));
        }
        return parentsCombination.flat();
    }

    _isPossibleCombination(product) {
        return product.attribute_lines.every(ptal => !ptal.attribute_values.find(
            ptav => ptal.selected_attribute_value_ids.includes(ptav.id)
        )?.excluded);
    }

    isPossibleConfiguration() {
        return [...this.state.products].every(p => this._isPossibleCombination(p));
    }

    _getCustomAttributeValues(product) {
        const customValues = [];
        for (const ptal of product.attribute_lines || []) {
            const selectedCustomPtav = ptal.attribute_values?.find(
                ptav => ptav.is_custom && ptal.selected_attribute_value_ids.includes(ptav.id)
            );

            if (selectedCustomPtav && ptal.customValue) {
                customValues.push({
                    ptav_id: selectedCustomPtav.id,
                    custom_value: ptal.customValue
                });
            }
        }
        return customValues;
    }

    _validateConditionalFiles() {
        const allProducts = [
            ...this.state.products,
            ...this.state.optionalProducts
        ];

        for (const product of allProducts) {
            if (!product.attribute_lines) continue;

            for (const ptal of product.attribute_lines) {
                // Check if any selected value requires a file
                const selectedPtavs = ptal.attribute_values.filter(v =>
                    ptal.selected_attribute_value_ids.includes(v.id)
                );

                const requiresFile = selectedPtavs.some(v => v.required_file);

                if (requiresFile) {
                    // Check if file is uploaded for this specific attribute line
                    const key = `${product.product_tmpl_id}_${ptal.id}`;
                    const hasFile = this.state.conditionalFileUploads[key];

                    if (!hasFile) {
                        return {
                            valid: false,
                            message: `Please upload a file for ${ptal.attribute.name}.`
                        };
                    }
                }
            }
        }
        return { valid: true };
    }

    _validateGelCoatRequirement() {
        const allProducts = [
            ...this.state.products,
            ...this.state.optionalProducts
        ];

        for (const product of allProducts) {
            if (!product.attribute_lines) continue;

            // Check if "Gel Coat REQ" is set to "Yes"
            let gelCoatRequired = false;
            for (const ptal of product.attribute_lines) {
                const attrName = ptal.attribute?.name?.toLowerCase() || '';
                if (attrName.includes('gel coat req') || attrName.includes('gelcoat req')) {
                    const selectedPtavs = ptal.attribute_values.filter(v =>
                        ptal.selected_attribute_value_ids.includes(v.id)
                    );

                    for (const ptav of selectedPtavs) {
                        if (ptav.name?.toLowerCase() === 'yes') {
                            gelCoatRequired = true;
                            console.log('🔍 Gel Coat REQ is set to Yes, validating Gel-coat selection');
                            break;
                        }
                    }
                    break;
                }
            }

            // If Gel Coat is required, check if it's selected
            if (gelCoatRequired) {
                for (const ptal of product.attribute_lines) {
                    if (ptal.attribute?.is_gelcoat_required_flag) {
                        const selectedPtavs = ptal.attribute_values.filter(v =>
                            ptal.selected_attribute_value_ids.includes(v.id)
                        );

                        // Check if a valid selection exists (not empty, not default placeholder)
                        const hasValidSelection = selectedPtavs.some(ptav => {
                            // For M2O attributes, check if m2o_res_id is set
                            if (ptal.attribute.display_type === 'm2o') {
                                return ptav.m2o_res_id && ptav.m2o_res_id > 0;
                            }
                            // For other types, check if name is not empty or placeholder
                            return ptav.name && ptav.name.trim() !== '' && !ptav.name.toLowerCase().includes('select');
                        });

                        if (!hasValidSelection) {
                            return {
                                valid: false,
                                message: `Gel-coat selection is required when "Gel Coat REQ" is set to "Yes". Please select a Gel-coat option.`
                            };
                        }
                    }
                }
            }
        }
        return { valid: true };
    }

    async onConfirm() {
        if (!this.isPossibleConfiguration()) return;

        // 🔥 NEW: Validate conditional files
        const validation = this._validateConditionalFiles();
        if (!validation.valid) {
            this.env.services.dialog.add(AlertDialog, {
                title: _t("Missing Required File"),
                body: validation.message,
                confirmLabel: _t("Ok"),
            });
            return;
        }

        // 🔥 NEW: Validate Gel-coat requirement
        const gelCoatValidation = this._validateGelCoatRequirement();
        if (!gelCoatValidation.valid) {
            this.env.services.dialog.add(AlertDialog, {
                title: _t("Gel-coat Required"),
                body: gelCoatValidation.message,
                confirmLabel: _t("Ok"),
            });
            return;
        }

        for (const product of this.state.products) {
            const needsVariant = !product.id && product.attribute_lines?.some(
                ptal => ptal.create_variant === "dynamic"
            );
            if (needsVariant) {
                const productId = await this._createProduct(product);
                product.id = parseInt(productId);
            }
        }

        const mainProduct = this.state.products.find(
            p => parseInt(p.product_tmpl_id) === parseInt(this.env.mainProductTmplId)
        );
        if (!mainProduct) return;

        const optionalProducts = this.state.products.filter(
            p => parseInt(p.product_tmpl_id) !== parseInt(this.env.mainProductTmplId)
        );

        const buildPayloadLine = (product) => {
            // 🔥 FIX: Get file from state instead of PTAV
            const file_upload = this._getFileUploadForProduct(product.product_tmpl_id);

            // 🔥 NEW: Get M2O values from state
            const m2o_values = this._getM2OValuesForProduct(product.product_tmpl_id);

            // NEW: Get conditional file upload from state
            const conditional_file_upload = this._getConditionalFileUploadForProduct(product.product_tmpl_id);

            return {
                product_id: parseInt(product.id),
                product_template_id: parseInt(product.product_tmpl_id),
                quantity: parseFloat(product.quantity) > 0 ? parseFloat(product.quantity) : 1,
                price: parseFloat(product.price) >= 0 ? parseFloat(product.price) : 0,

                // 🔥 Filter out file_upload AND m2o PTAVs
                ptav_ids: this._getCombination(product)
                    .filter(id => {
                        const ptav = product.attribute_lines
                            .flatMap(a => a.attribute_values)
                            .find(v => v.id === id);
                        const displayType = ptav?.attribute_id?.display_type;
                        return displayType !== "file_upload" && displayType !== "m2o";
                    })
                    .map(id => parseInt(id)),

                custom_attribute_values: this._getCustomAttributeValues(product),
                file_upload: file_upload,
                m2o_values: m2o_values, // 🔥 NEW
                conditional_file_upload: conditional_file_upload, // NEW
            };
        };

        const crmLeadId = parseInt(this.props.crmLeadId);
        if (!crmLeadId) return;

        const payload = {
            main_product: buildPayloadLine(mainProduct),
            optional_products: optionalProducts.map(buildPayloadLine),
            crm_lead_id: crmLeadId,
        };

        console.log("🔍 Built payload:", payload);
        console.log("🔍 File upload in payload:", payload.main_product.file_upload);
        console.log("🔍 M2O values in payload:", payload.main_product.m2o_values);

        try {
            const res = await this.rpc('/crm_product_configurator/save_to_crm', payload);
            if (res && res.success) {
                this.props.close?.();
            } else {
                console.error("Error saving to CRM:", res?.error || "Unknown error");
            }
        } catch (err) {
            console.error("RPC failed:", err);
        }
    }

    onDiscard() {
        try {
            if (!this.props.edit && typeof this.props.discard === 'function') {
                this.props.discard();
            }
            this.props.close?.();
        } catch (err) {
            console.error("Discard error:", err);
        }
    }
}