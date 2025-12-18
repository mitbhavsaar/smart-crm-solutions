import { x2ManyCommands } from "@web/core/orm_service";
import { _t } from "@web/core/l10n/translation";
import { helpers } from "@odoo/o-spreadsheet";
import { OdooUIPlugin } from "@spreadsheet/plugins";

const { positionToZone } = helpers;

export class FieldSyncUIPlugin extends OdooUIPlugin {
    static getters = ["getFieldSyncX2ManyCommands"];
    static layers = ["Triangle"];

    handle(cmd) {
        switch (cmd.type) {
            case "AUTOFILL_CELL": {
                const sheetId = this.getters.getActiveSheetId();
                const origin = this.getters.getFieldSync({
                    sheetId,
                    col: cmd.originCol,
                    row: cmd.originRow,
                });
                if (origin) {
                    const targetCol = cmd.col;
                    const targetRow = cmd.row;
                    const delta = targetRow - cmd.originRow;
                    this.dispatch("ADD_FIELD_SYNC", {
                        sheetId,
                        col: targetCol,
                        row: targetRow,
                        listId: origin.listId,
                        fieldName: origin.fieldName,
                        indexInList: origin.indexInList + delta,
                    });
                }
                break;
            }
        }
    }

    /**
     * ✅ FIXED: Get ACTUAL record ID from list domain
     */
    async getRecordIdFromList(listId, indexInList = 0) {
        try {
            console.log(`🔍 [getRecordIdFromList] List: ${listId}, Index: ${indexInList}`);
            
            const list = this.getters.getListDefinition(listId);
            if (!list) {
                console.error(`❌ List definition not found: ${listId}`);
                return null;
            }

            const domain = list.domain || [];
            let recordId = null;

            for (const condition of domain) {
                if (!Array.isArray(condition) || condition.length < 3) {
                    continue;
                }

                const [field, operator, value] = condition;
                
                if (field === 'id' && operator === '=') {
                    recordId = parseInt(value);
                    break;
                }
                
                if (field === 'id' && operator === 'in' && Array.isArray(value)) {
                    if (indexInList < value.length) {
                        recordId = parseInt(value[indexInList]);
                    }
                    break;
                }
            }

            if (!recordId) {
                console.error(`❌ No record ID found in domain for list ${listId}`);
                console.error(`Domain was:`, domain);
                return null;
            }

            console.log(`✅ [getRecordIdFromList] List ${listId} -> Record ID: ${recordId}`);
            return recordId;

        } catch (error) {
            console.error(`❌ Error in getRecordIdFromList:`, error);
            return null;
        }
    }

    /**
     * ✅ CRITICAL FIX: Get commands for ALL sheets, not just active sheet
     */
    async getFieldSyncX2ManyCommands() {
        const commands = [];
        const errors = [];

        try {
            const allLists = this.getters.getMainLists();

            if (!allLists || allLists.length === 0) {
                return { commands: [], errors: [] };
            }

            console.log(`📊 Processing ${allLists.length} lists from ALL sheets`);

            for (const list of allLists) {
                // ❌ REMOVED: list.sheetId !== activeSheetId check
                // ✅ NOW: Process ALL lists from ALL sheets

                console.log(`📋 Processing list: ${list.id} (${list.name}) from sheet: ${list.sheetId}`);

                const recordId = await this.getRecordIdFromList(list.id, 0);
                
                if (!recordId) {
                    console.error(`❌ No record ID for list ${list.id}, skipping`);
                    errors.push(`No record found for list ${list.id}`);
                    continue;
                }

                console.log(`✅ List ${list.id} -> Record ID: ${recordId}`);

                const recordUpdates = {};
                const allFieldSyncs = [...this.getters.getAllFieldSyncs()];
                
                for (const [position, fieldSync] of allFieldSyncs) {
                    // ✅ CHANGED: Remove sheetId check - process field syncs from ALL sheets
                    if (fieldSync.listId !== list.id) {
                        continue;
                    }

                    const { fieldName } = fieldSync;
                    const cell = this.getters.getEvaluatedCell(position);
                    
                    if (cell.type === "empty" || cell.value === "" || cell.value === null) {
                        continue;
                    }

                    // ✅ Use formattedValue for all fields
                    let serverValue;
                    
                    if (cell.type === "number") {
                        serverValue = cell.value;
                    } else if (cell.type === "boolean") {
                        serverValue = cell.value;
                    } else {
                        serverValue = cell.formattedValue || cell.value || "";
                    }
                    
                    recordUpdates[fieldName] = serverValue;
                    console.log(`📝 Field ${fieldName} = ${serverValue} from sheet: ${position.sheetId}`);
                }

                if (Object.keys(recordUpdates).length > 0) {
                    commands.push(x2ManyCommands.update(recordId, recordUpdates));
                    console.log(`✅ Command created for record ${recordId}:`, recordUpdates);
                } else {
                    console.log(`⚠️ No updates for list ${list.id}`);
                }
            }

            console.log(`\n📦 Total commands from ALL sheets: ${commands.length}`);
            console.log(`⚠️ Total errors: ${errors.length}`);

        } catch (error) {
            const errorMsg = `Critical error: ${error.message}`;
            console.error(`❌ ${errorMsg}`, error);
            errors.push(errorMsg);
        }

        return { commands, errors };
    }

    getActiveSheetListIds() {
        const activeSheetId = this.getters.getActiveSheetId();
        const allLists = this.getters.getMainLists();
        
        return allLists
            .filter(list => list.sheetId === activeSheetId)
            .map(list => list.id);
    }

    isFieldSyncFromActiveSheet(fieldSync, position) {
        const activeSheetId = this.getters.getActiveSheetId();
        const activeSheetLists = this.getActiveSheetListIds();
        
        return position.sheetId === activeSheetId && 
               activeSheetLists.includes(fieldSync.listId);
    }

    getFieldSyncsForList(listId) {
        const fieldSyncs = [];
        
        try {
            const allFieldSyncs = this.getters.getAllFieldSyncs();
            
            if (allFieldSyncs instanceof Map) {
                for (const [key, fieldSync] of allFieldSyncs) {
                    if (fieldSync.listId === listId) {
                        const position = this.parsePositionFromKey(key);
                        fieldSyncs.push({
                            ...fieldSync,
                            ...position
                        });
                    }
                }
            } else if (Array.isArray(allFieldSyncs)) {
                for (const fieldSync of allFieldSyncs) {
                    if (fieldSync.listId === listId) {
                        fieldSyncs.push(fieldSync);
                    }
                }
            } else if (typeof allFieldSyncs === 'object') {
                for (const [positionKey, fieldSync] of Object.entries(allFieldSyncs)) {
                    if (fieldSync.listId === listId) {
                        const position = this.parsePositionFromKey(positionKey);
                        fieldSyncs.push({
                            ...fieldSync,
                            ...position
                        });
                    }
                }
            }
        } catch (error) {
            console.error("Error getting field syncs for list:", error);
        }
        
        return fieldSyncs;
    }

    parsePositionFromKey(key) {
        try {
            if (key.includes('_')) {
                const parts = key.split('_');
                if (parts.length >= 3) {
                    return {
                        sheetId: parts[0],
                        col: parseInt(parts[1]),
                        row: parseInt(parts[2])
                    };
                }
            }
            
            const position = JSON.parse(key);
            if (position.sheetId && position.col !== undefined && position.row !== undefined) {
                return position;
            }
        } catch {
            // Parsing failed
        }
        
        return { sheetId: this.getters.getActiveSheetId(), col: 0, row: 0 };
    }

    async checkFieldConflicts() {
        const errors = [];
        const lists = this.getters.getMainLists();
        
        for (const list of lists) {
            const listFieldSyncs = this.getFieldSyncsForList(list.id);
            const syncsByIndex = {};
            
            for (const fieldSync of listFieldSyncs) {
                const index = fieldSync.indexInList;
                if (!syncsByIndex[index]) {
                    syncsByIndex[index] = [];
                }
                syncsByIndex[index].push(fieldSync);
            }

            for (const [indexInList, fieldSyncs] of Object.entries(syncsByIndex)) {
                const recordId = await this.getRecordIdFromList(list.id, parseInt(indexInList));
                if (!recordId) continue;

                const fieldCount = {};
                
                for (const fieldSync of fieldSyncs) {
                    const position = { 
                        sheetId: fieldSync.sheetId, 
                        col: fieldSync.col, 
                        row: fieldSync.row 
                    };
                    const cell = this.getters.getEvaluatedCell(position);
                    
                    if (cell.type !== "empty" && cell.value !== "") {
                        fieldCount[fieldSync.fieldName] = (fieldCount[fieldSync.fieldName] || 0) + 1;
                    }
                }

                for (const [fieldName, count] of Object.entries(fieldCount)) {
                    if (count > 1) {
                        errors.push(
                            _t(
                                "Record %s field '%s' is being updated by %s cells",
                                recordId,
                                fieldName,
                                count
                            )
                        );
                    }
                }
            }
        }

        return errors;
    }

    getFieldTypeSpec(fieldType, fieldName) {
        if (!fieldType) {
            return {
                checkType: (cell) => true,
                error: "",
                castToServerValue: (cell) => cell.formattedValue,
            };
        }
        
        switch (fieldType) {
            case "float":
            case "monetary":
                return {
                    checkType: (cell) => cell.type === "number",
                    error: _t("It should be a number."),
                    castToServerValue: (cell) => cell.value,
                };
            case "many2one":
                return {
                    checkType: (cell) => cell.type === "number" && Number.isInteger(cell.value),
                    error: _t("It should be an integer ID."),
                    castToServerValue: (cell) => cell.value,
                };
            case "integer":
                return {
                    checkType: (cell) => cell.type === "number" && Number.isInteger(cell.value),
                    error: _t("It should be an integer."),
                    castToServerValue: (cell) => cell.value,
                };
            case "boolean":
                return {
                    checkType: (cell) => cell.type === "boolean",
                    error: _t("It should be TRUE or FALSE."),
                    castToServerValue: (cell) => cell.value,
                };
            case "char":
            case "text":
            default:
                return {
                    checkType: (cell) => true,
                    error: "",
                    castToServerValue: (cell) => cell.formattedValue,
                };
        }
    }

    drawLayer({ ctx }, layer) {
        const activeSheetId = this.getters.getActiveSheetId();
        
        try {
            const allFieldSyncs = this.getters.getAllFieldSyncs();
            let fieldSyncEntries = [];

            if (allFieldSyncs instanceof Map) {
                fieldSyncEntries = Array.from(allFieldSyncs.entries());
            } else if (Array.isArray(allFieldSyncs)) {
                fieldSyncEntries = allFieldSyncs.map((sync, index) => [index, sync]);
            } else if (typeof allFieldSyncs === 'object') {
                fieldSyncEntries = Object.entries(allFieldSyncs);
            }

            for (const [key, fieldSync] of fieldSyncEntries) {
                const position = this.parsePositionFromKey(key);
                
                if (position.sheetId !== activeSheetId) {
                    continue;
                }

                const zone = this.getters.expandZone(activeSheetId, positionToZone(position));
                if (zone.left !== position.col || zone.top !== position.row) {
                    continue;
                }

                const { x, y, width } = this.getters.getVisibleRect(zone);
                ctx.fillStyle = "#6C4E65";
                ctx.beginPath();
                ctx.moveTo(x + width - 5, y);
                ctx.lineTo(x + width, y);
                ctx.lineTo(x + width, y + 5);
                ctx.fill();
            }
        } catch (error) {
            console.error("Error drawing field sync layer:", error);
        }
    }
}