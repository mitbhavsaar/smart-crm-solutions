/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { WarningDialog } from "@web/core/errors/error_dialogs";
import { AbstractSpreadsheetAction } from "@spreadsheet_edition/bundle/actions/abstract_spreadsheet_action";
import { useSubEnv } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useSpreadsheetFieldSyncExtension } from "../field_sync_extension_hook";

export class SpreadsheetFieldSyncAction extends AbstractSpreadsheetAction {
    static template = "crm_customisation.CrmLeadSpreadsheetAction";
    static path = "crm-lead-spreadsheet";
    
    // ❌ REMOVE THIS LINE - Don't set static resModel
    // resModel = "crm.lead.spreadsheet";

    setup() {
        super.setup();
        
        this.dialogService = useService("dialog");
        this.notificationService = useService("notification");
        this.orm = useService("orm");
        
        this.notificationMessage = _t("Calculator ready");
        useSubEnv({ makeCopy: this.makeCopy.bind(this) });
        useSpreadsheetFieldSyncExtension();
        
        // ✅ Initialize with default values
        this.spreadsheetType = 'crm';  // Default to CRM
        this._resModel = 'crm.lead.spreadsheet';  // Default model
        this.leadId = null;
        this.saleOrderId = null;
        this.spreadsheetId = null;
    }

    /**
     * Get main lists from spreadsheet data
     */
    getMainLists() {
        if (!this.spreadsheetData || !this.spreadsheetData.lists) {
            return [];
        }

        const lists = [];
        const listData = this.spreadsheetData.lists;

        for (const [listId, listConfig] of Object.entries(listData)) {
            lists.push({
                id: listId,
                model: listConfig.model,
                domain: listConfig.domain,
                columns: listConfig.columns,
                sheetId: listConfig.sheetId,
                name: listConfig.name,
                context: listConfig.context || {},
                orderBy: listConfig.orderBy || [],
            });
        }

        return lists;
    }

    async writeToParent() {
        try {
            const { commands, errors } = await this.model.getters.getFieldSyncX2ManyCommands();

            if (errors.length) {
                this.dialogService.add(WarningDialog, {
                    title: _t("Unable to Save"),
                    message: errors.join("\n\n"),
                });
                return;
            }

            console.log(`💾 [${this.spreadsheetType.toUpperCase()}] Saving ${commands.length} commands`);
            
            // ✅ Process commands based on spreadsheet type
            if (this.spreadsheetType === 'crm' && this.leadId) {
                console.log(`💾 Writing to crm.lead ${this.leadId}`);
                await this.orm.write("crm.lead", [this.leadId], {
                    material_line_ids: commands,
                });
                
            } else if (this.spreadsheetType === 'sale' && this.saleOrderId) {
                console.log(`💾 Writing to sale.order ${this.saleOrderId}`);
                await this.orm.write("sale.order", [this.saleOrderId], {
                    order_line: commands,
                });
            } else {
                throw new Error(`No valid parent record found. Type: ${this.spreadsheetType}, LeadId: ${this.leadId}, OrderId: ${this.saleOrderId}`);
            }
       
            this.notificationService.add(
                _t("Successfully saved %s changes", commands.length), 
                { type: "success" }
            );
            
            this.env.config.historyBack();
            
        } catch (error) {
            console.error("❌ Save error:", error);
            this.dialogService.add(WarningDialog, {
                title: _t("Save Error"),
                message: _t("Failed to save changes: %s", error.message),
            });
        }
    }

    /**
     * ✅ CRITICAL FIX: Initialize with backend data and set model
     */
    _initializeWith(data) {
        super._initializeWith(data);
        
        console.log("🔵 [INIT] Received data:", data);
        
        // ✅ CRITICAL: Detect model from backend data FIRST
        const backendModel = data.model || null;
        
        if (backendModel === 'sale.order.spreadsheet' || data.sale_order_id) {
            // ✅ Sale Order spreadsheet
            this.spreadsheetType = 'sale';
            this._resModel = 'sale.order.spreadsheet';
            this.saleOrderId = data.sale_order_id;
            this.orderDisplayName = data.order_display_name;
            console.log("✅ Detected SALE spreadsheet");
            
        } else if (backendModel === 'crm.lead.spreadsheet' || data.lead_id) {
            // ✅ CRM Lead spreadsheet
            this.spreadsheetType = 'crm';
            this._resModel = 'crm.lead.spreadsheet';
            this.leadId = data.lead_id;
            this.leadDisplayName = data.lead_display_name;
            console.log("✅ Detected CRM spreadsheet");
            
        } else {
            // ✅ Default to CRM if unsure
            console.warn("⚠️ Could not detect spreadsheet type, defaulting to CRM");
            this.spreadsheetType = 'crm';
            this._resModel = 'crm.lead.spreadsheet';
        }
        
        this.spreadsheetId = data.sheet_id;
        this.backendData = data;
        
        console.log("✅ [INIT] Final state:");
        console.log(`   Type: ${this.spreadsheetType}`);
        console.log(`   Model: ${this._resModel}`);
        console.log(`   LeadId: ${this.leadId}`);
        console.log(`   OrderId: ${this.saleOrderId}`);
    }
    
    /**
     * ✅ CRITICAL: Return the dynamically set model
     */
    get resModel() {
        return this._resModel;
    }
    
    /**
     * Get appropriate button label based on type
     */
    get saveButtonLabel() {
        if (this.spreadsheetType === 'crm' && this.leadId) {
            const leadName = this.leadDisplayName || this.backendData?.lead_display_name || 'Lead';
            return _t("Save in %s", leadName);
        } else if (this.spreadsheetType === 'sale' && this.saleOrderId) {
            const orderName = this.orderDisplayName || this.backendData?.order_display_name || 'Order';
            return _t("Save in %s", orderName);
        }
        return _t("Save");
    }

    /**
     * Get current record ID based on type
     */
    get currentRecordId() {
        if (this.spreadsheetType === 'crm') {
            return this.leadId;
        } else if (this.spreadsheetType === 'sale') {
            return this.saleOrderId;
        }
        return null;
    }

    /**
     * Enhanced error handling for spreadsheet loading
     */
    async loadSpreadsheet() {
        try {
            await super.loadSpreadsheet();
        } catch (error) {
            console.error("❌ Load error:", error);
            this.dialogService.add(WarningDialog, {
                title: _t("Load Error"),
                message: _t("Failed to load spreadsheet: %s", error.message),
            });
        }
    }
}

// ✅ Register BOTH actions with SAME class
registry.category("actions").add("action_crm_lead_spreadsheet", SpreadsheetFieldSyncAction, { force: true });
registry.category("actions").add("action_sale_order_spreadsheet", SpreadsheetFieldSyncAction, { force: true });

console.log("✅ Registered unified SpreadsheetFieldSyncAction for both CRM and Sale");