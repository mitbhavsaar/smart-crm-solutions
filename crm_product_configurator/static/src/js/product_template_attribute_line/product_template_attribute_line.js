/** @odoo-module */

import { Component } from "@odoo/owl";
import { formatCurrency } from "@web/core/currency";
import { onMounted } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class ProductTemplateAttributeLine extends Component {
    static template = "crmProductConfigurator.ptal";

    static props = {
        productTmplId: Number,
        id: Number,
        attribute: {
            type: Object,
            shape: {
                id: Number,
                name: String,
                display_type: {
                    type: String,
                    validate: t =>
                        ["color", "multi", "pills", "radio", "select", "file_upload", "m2o", "strictly_numeric"].includes(t),
                },
                m2o_model_id: { type: [Boolean, Object], optional: true },
                m2o_values: { type: Array, element: Object, optional: true },
                pair_with_previous: { type: Boolean, optional: true }, // 🔥 NEW
                is_width_check: { type: Boolean, optional: true }, // 🔥 NEW
                m2o_model_technical_name: { type: [String, Boolean], optional: true }, // 🔥 NEW
                is_gelcoat_required_flag: { type: Boolean, optional: true }, // 🔥 NEW
                is_quantity: { type: Boolean, optional: true }, // 🔥 NEW - Fix for OwlError
            },
        },
        attribute_values: {
            type: Array,
            element: {
                type: Object,
                shape: {
                    id: Number,
                    name: String,
                    html_color: [Boolean, String],
                    image: [Boolean, String],
                    is_custom: Boolean,
                    excluded: { type: Boolean, optional: true },
                    m2o_res_id: { optional: true },
                    required_file: { type: Boolean, optional: true }, // NEW: Track if file is required

                },
            },
        },
        selected_attribute_value_ids: { type: Array, element: Number },
        create_variant: {
            type: String,
            validate: t => ["always", "dynamic", "no_variant"].includes(t),
        },
        customValue: { type: [{ value: false }, String], optional: true },
        m2o_values: { type: Array, element: Object, optional: true },
    };

    setup() {
        // 🔥 CRITICAL FIX: Initialize fresh file state (never load from PTAV)
        this.fileState = {
            fileName: null,
            fileData: null,
        };

        // NEW: Initialize conditional file state
        this.conditionalFileState = {
            fileName: null,
            fileData: null,
        };

        // 🔥 NEW: M2O state - always start with no selection
        this.m2oSelectedId = null;

        // NEW: Initialize numeric warning state
        this.numericWarning = "";

        onMounted(() => {
            // 🔥 FIX: Syntax error thik kiya - M2O ko exclude karein
            if (
                this.props.attribute_values.length === 1 &&
                this.props.selected_attribute_value_ids.length === 0 &&
                this.props.attribute.display_type !== "m2o" // ✅ M2O ko exclude karein
            ) {
                this.updateSelectedPTAV({
                    target: { value: this.props.attribute_values[0].id.toString() },
                });
            }

            // 🔥 NEW: M2O ke liye explicitly clear selection
            if (this.props.attribute.display_type === "m2o") {
                this.m2oSelectedId = null;

                // Parent ko bhi notify karein
                if (this.env.updateM2OValue) {
                    this.env.updateM2OValue(
                        this.props.productTmplId,
                        this.props.id,
                        null
                    );
                }
            }
        });
    }

    // -----------------------------
    // DEFAULT PTAV UPDATE
    // -----------------------------
    updateSelectedPTAV(event) {
        this.env.updateProductTemplateSelectedPTAV(
            this.props.productTmplId,
            this.props.id,
            event.target.value,
            this.props.attribute.display_type === "multi"
        );
    }

    updateCustomValue(event) {
        this.env.updatePTAVCustomValue(
            this.props.productTmplId,
            this.props.selected_attribute_value_ids[0],
            event.target.value
        );
    }

    // -----------------------------
    // TEMPLATE SELECTION
    // -----------------------------
    getPTAVTemplate() {
        switch (this.props.attribute.display_type) {
            case "color":
                return "crmProductConfigurator.ptav-color";
            case "multi":
                return "crmProductConfigurator.ptav-multi";
            case "pills":
                return "crmProductConfigurator.ptav-pills";
            case "radio":
                return "crmProductConfigurator.ptav-radio";
            case "select":
                return "crmProductConfigurator.ptav-select";
            case "file_upload":
                return "entrivis_file_upload.ptav-file-upload";
            case "m2o":
                return "crmProductConfigurator.ptav-m2o";
            case "strictly_numeric":
                return "crmProductConfigurator.ptav-strictly-numeric";
        }
    }

    getPTAVSelectName(ptav) {
        return ptav.name;
    }

    isSelectedPTAVCustom() {
        return this.props.attribute_values.find(
            ptav => this.props.selected_attribute_value_ids.includes(ptav.id)
        )?.is_custom;
    }

    hasPTAVCustom() {
        return this.props.attribute_values.some(ptav => ptav.is_custom);
    }

    isSingleValueReadOnly() {
        return (
            this.props.attribute_values.length === 1 &&
            !this.hasPTAVCustom()
        );
    }

    // -----------------------------
    // FILE UPLOAD LOGIC - ALWAYS FRESH
    // -----------------------------
    getSelectedPTAV() {
        return this.props.attribute_values.find(v =>
            this.props.selected_attribute_value_ids.includes(v.id)
        );
    }

    // 🔥 FIX: Return fresh file state, never from PTAV
    getFileName() {
        return this.fileState.fileName || "";
    }

    // 🔥 FIX: Store file in component state, send to parent via env callback
    async uploadFile(ev) {
        const file = ev.target.files[0];
        if (!file) return;

        const reader = new FileReader();

        reader.onload = async e => {
            const base64 = e.target.result.split(",")[1];

            // Store in component state
            this.fileState.fileName = file.name;
            this.fileState.fileData = base64;

            // 🔥 NEW: Notify parent dialog to store file payload
            if (this.env.updateFileUpload) {
                this.env.updateFileUpload(
                    this.props.productTmplId,
                    this.props.id,
                    {
                        file_name: file.name,
                        file_data: base64,
                    }
                );
            }

            this.render(); // refresh UI
        };

        reader.readAsDataURL(file);
    }

    removeUploadedFile() {
        this.fileState.fileName = null;
        this.fileState.fileData = null;

        // notify dialog to reset file payload
        if (this.env.updateFileUpload) {
            this.env.updateFileUpload(
                this.props.productTmplId,
                this.props.id,
                null  // reset file payload completely
            );
        }

        this.render();
    }

    // -----------------------------
    // STRICTLY NUMERIC VALIDATION
    // -----------------------------
    validateNumeric(event) {
        const value = event.target.value;
        const isValid = /^[0-9]*$/.test(value);

        if (!isValid) {
            this.numericWarning = "Numeric Values Only !";
        } else {
            this.numericWarning = "";
        }

        // restrict input visually
        event.target.value = value.replace(/[^0-9]/g, "");

        // save the cleaned numeric value
        this.updateCustomValue(event);
        this.render();
    }


    async updateSelectedM2O(ev) {
        const value = ev.target.value;

        // empty selection
        if (value === "") {
            this.m2oSelectedId = null;
            if (this.env.updateM2OValue) {
                this.env.updateM2OValue(
                    this.props.productTmplId,
                    this.props.id,
                    null
                );
            }
            this.render();
            return;
        }

        const resId = parseInt(value);
        this.m2oSelectedId = resId;

        // normal M2O propagate
        if (this.env.updateM2OValue) {
            this.env.updateM2OValue(
                this.props.productTmplId,
                this.props.id,
                resId
            );
        }

        // only profile → width autofill
        if (this.props.attribute.m2o_model_id?.model === "profile.name") {
            const result = await rpc("/web/dataset/call_kw/profile.name/read", {
                model: "profile.name",
                method: "read",
                args: [[resId], ["width"]],
                kwargs: {},
            });

            const width = result?.length ? result[0].width : false;

            // width found → autofill
            if (width || width === 0) {
                if (this.env.autoFillWidthFromM2O) {
                    this.env.autoFillWidthFromM2O(
                        this.props.productTmplId,
                        String(width),
                    );
                }

                // refresh UI immediately
                this.render();
                return;
            }

            // width missing → allow manual custom text input
            this.render();
            return;
        }

        console.log("🔍 Profile selected, fetching width...");

        // read width from profile
        let result = false;
        try {
            result = await rpc("/web/dataset/call_kw/profile.name/read", {
                model: "profile.name",
                method: "read",
                args: [[resId], ["width"]],
                kwargs: {},
            });
        } catch (e) {
            console.error("❌ RPC error:", e);
        }

        const width = result?.length ? result[0].width : false;
        console.log("📊 Width from profile:", width);

        // if width null → do not autofill
        if (!width && width !== 0) {
            console.log("⚠️ No width value, skipping autofill");
            this.render();
            return;
        }

        // ✅ Notify dialog to autofill width
        if (this.env.autoFillWidthFromM2O) {
            console.log("✅ Calling autoFillWidthFromM2O with width:", width);
            this.env.autoFillWidthFromM2O(
                this.props.productTmplId,
                String(width)
            );
        }

        // Don't render - let parent dialog handle it
    }


    getSelectedM2OId() {
        // 🔥 FIX: Always use component state, never from PTAV
        return this.m2oSelectedId;
    }

    // -----------------------------
    // CONDITIONAL FILE UPLOAD LOGIC
    // -----------------------------

    /**
     * Check if conditional file upload should be shown
     * Only show if:
     * 1. Display type is radio or select
     * 2. A value is selected
     * 3. The selected value has required_file = true
     */
    shouldShowConditionalFileUpload() {
        // Only for radio/select display types
        if (!['radio', 'select'].includes(this.props.attribute.display_type)) {
            return false;
        }

        // Get selected value
        const selectedPTAV = this.props.attribute_values.find(v =>
            this.props.selected_attribute_value_ids.includes(v.id)
        );

        console.log("🔍 Checking conditional file upload:", {
            attribute: this.props.attribute.name,
            display_type: this.props.attribute.display_type,
            selected_ids: this.props.selected_attribute_value_ids,
            selectedPTAV: selectedPTAV,
            required_file: selectedPTAV ? selectedPTAV.required_file : 'N/A'
        });

        // Show if selected value has required_file flag
        return selectedPTAV && selectedPTAV.required_file;
    }

    /**
     * Get conditional file name
     */
    getConditionalFileName() {
        return this.conditionalFileState.fileName || "";
    }

    /**
     * Upload conditional file
     */
    async uploadConditionalFile(ev) {
        const file = ev.target.files[0];
        if (!file) return;

        const reader = new FileReader();

        reader.onload = async e => {
            const base64 = e.target.result.split(",")[1];

            // Store in component state
            this.conditionalFileState.fileName = file.name;
            this.conditionalFileState.fileData = base64;

            // Notify parent dialog to store conditional file payload
            if (this.env.updateConditionalFileUpload) {
                this.env.updateConditionalFileUpload(
                    this.props.productTmplId,
                    this.props.id,
                    {
                        file_name: file.name,
                        file_data: base64,
                    }
                );
            }

            this.render(); // refresh UI
        };

        reader.readAsDataURL(file);
    }

    /**
     * Remove conditional file
     */
    removeConditionalFile() {
        this.conditionalFileState.fileName = null;
        this.conditionalFileState.fileData = null;

        // Notify dialog to reset conditional file payload
        if (this.env.updateConditionalFileUpload) {
            this.env.updateConditionalFileUpload(
                this.props.productTmplId,
                this.props.id,
                null  // reset file payload completely
            );
        }

        this.render();
    }
}