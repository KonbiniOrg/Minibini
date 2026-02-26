# Line Item Type UI Test Dataset Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a clean, comprehensive test fixture dataset designed specifically for UI testing of LineItemType functionality across Estimates, Invoices, Purchase Orders, and Bills.

**Architecture:** Single consolidated fixture file with carefully designed data covering all LineItemType UI scenarios. Objects are designed with clear naming that indicates their purpose in testing.

**Tech Stack:** Django fixtures (JSON), pytest for validation

---

## Design Principles

1. **Clean slate data** - No orphaned records or unreachable states
2. **Self-documenting** - Names and descriptions indicate testing purpose
3. **Comprehensive coverage** - All LineItemType scenarios covered
4. **Minimal but sufficient** - Only objects needed for testing, no bloat

---

## Data Objects Required

### 1. LineItemTypes (6 types)

| PK | Code | Name | Taxable | Purpose |
|----|------|------|---------|---------|
| 1 | SVC | Service | false | Labor, professional services |
| 2 | MAT | Material | true | Raw materials, supplies |
| 3 | MFR | Manufacturing | true | Processes involved in creating a salable physical object |
| 4 | PRD | Product | true | Finished goods |
| 5 | FRT | Freight | false | Shipping, delivery |
| 6 | OVH | Overhead | false | Admin fees, permits |

### 2. Configuration (base settings)

- Number sequences for jobs, estimates, invoices, POs, bills
- Counters set to 100 (to avoid conflicts with manual test data)
- `default_tax_rate`: "0.08" (8%)

### 3. Users (3 users)

| Username | Role | Has Contact | Purpose |
|----------|------|-------------|---------|
| testadmin | Administrator | Yes (Contact 1) | Full access testing |
| testmgr | Manager | Yes (Contact 2) | Manager workflow testing |
| testuser | Employee | Yes (Contact 5) | Limited access testing |

### 4. Businesses (2 businesses)

| Name | Purpose | Tax Status |
|------|---------|------------|
| "Acme Supplies Inc" | Vendor for POs/Bills | Normal (taxable) |
| "Widget Corp" | Customer with 2 contacts | Has tax exemption |

### 5. Contacts (5 contacts)

| # | Name | Business | Purpose |
|---|------|----------|---------|
| 1 | "Single Individual" | None | User contact, solo customer |
| 2 | "Manager Person" | Widget Corp | User contact, business employee |
| 3 | "Alice Widget" | Widget Corp | 2nd contact same business |
| 4 | "Bob Acme" | Acme Supplies | Vendor contact |
| 5 | "Solo Customer" | None | Independent customer |

### 6. PriceListItems (7 items - one per LineItemType + extra)

| PK | Code | Type | Description | Sell Price | Purpose |
|----|------|------|-------------|------------|---------|
| 1 | PLI-SVC-01 | SVC | "Consultation Hour" | 95.00 | Service line item |
| 2 | PLI-MAT-01 | MAT | "Lumber 2x4x8" | 12.50 | Material line item |
| 3 | PLI-MFR-01 | MFR | "CNC Machining Hour" | 125.00 | Manufacturing line item |
| 4 | PLI-PRD-01 | PRD | "Custom Cabinet" | 850.00 | Product line item |
| 5 | PLI-FRT-01 | FRT | "Standard Shipping" | 45.00 | Non-taxable freight |
| 6 | PLI-OVH-01 | OVH | "Permit Fee" | 150.00 | Non-taxable overhead |
| 7 | PLI-MAT-02 | MAT | "Hardware Kit" | 35.00 | Second material for variety |

### 7. TaskMappings (4 mappings linked to LineItemTypes)

| PK | step_type | Strategy | default_product_type | Output LineItemType | Purpose |
|----|-----------|----------|----------------------|---------------------|---------|
| 1 | labor | direct | (blank) | SVC | Labor → Service line items |
| 2 | material | direct | (blank) | MAT | Material → Material line items |
| 3 | component | bundle_to_product | "cabinet" | PRD | Cabinet components → bundled Product |
| 4 | overhead | exclude | (blank) | OVH | Internal tasks, excluded from estimates |

### 8. TaskTemplates (6 templates)

| PK | Name | Mapping | Units | Rate | Purpose |
|----|------|---------|-------|------|---------|
| 1 | "Basic Labor" | 1 (labor) | hours | 75.00 | Direct service tasks |
| 2 | "Material Handling" | 2 (material) | each | 25.00 | Direct material tasks |
| 3 | "Cabinet Frame" | 3 (component) | each | 200.00 | Bundled: cabinet frame |
| 4 | "Cabinet Doors" | 3 (component) | each | 150.00 | Bundled: cabinet doors |
| 5 | "Cabinet Finish" | 3 (component) | each | 100.00 | Bundled: cabinet finishing |
| 6 | "Shop Overhead" | 4 (overhead) | hours | 50.00 | Internal, excluded |

### 9. WorksheetTemplates (2 templates)

| PK | Name | Type | product_type | base_price | Tasks | Purpose |
|----|------|------|--------------|------------|-------|---------|
| 1 | "Simple Service" | service | (blank) | null | Basic Labor, Material Handling | Direct line items only |
| 2 | "Cabinet Build" | product | "cabinet" | 450.00 | Cabinet Frame, Cabinet Doors, Cabinet Finish, Shop Overhead | Bundling test template |

### 9a. TemplateTaskAssociations

| PK | WorksheetTemplate | TaskTemplate | est_qty | sort_order |
|----|-------------------|--------------|---------|------------|
| 1 | 1 (Simple Service) | 1 (Basic Labor) | 4.00 | 1 |
| 2 | 1 (Simple Service) | 2 (Material Handling) | 2.00 | 2 |
| 3 | 2 (Cabinet Build) | 3 (Cabinet Frame) | 1.00 | 1 |
| 4 | 2 (Cabinet Build) | 4 (Cabinet Doors) | 2.00 | 2 |
| 5 | 2 (Cabinet Build) | 5 (Cabinet Finish) | 1.00 | 3 |
| 6 | 2 (Cabinet Build) | 6 (Shop Overhead) | 2.00 | 4 |

### 9b. ProductBundlingRules (for testing bundling → LineItemType)

| PK | rule_name | product_type | work_order_template | line_item_template | combine_instances | pricing_method | include_materials | include_labor | include_overhead |
|----|-----------|--------------|---------------------|-------------------|-------------------|----------------|-------------------|---------------|------------------|
| 1 | "Cabinet Bundler" | "cabinet" | 2 (Cabinet Build) | "Custom Cabinet - {product_identifier}" | true | sum_components | true | true | false |

**How bundling works:**
- Tasks with TaskMapping.mapping_strategy = 'bundle_to_product' and TaskMapping.default_product_type = 'cabinet'
- Are grouped by their TaskInstanceMapping.product_identifier
- ProductBundlingRule matches on product_type and defines how to create the line item
- Result: Multiple component tasks → single EstimateLineItem with type PRD

### 10. Jobs (5 jobs - various states)

| PK | Contact | Status | Has Worksheet | Has Estimate | Purpose |
|----|---------|--------|---------------|--------------|---------|
| 1 | Contact 1 | draft | No | No | Empty job |
| 2 | Contact 2 | draft | Yes (WS 1) | No | Worksheet only, direct tasks |
| 3 | Contact 3 | draft | No | Yes (Est 1, empty) | Empty estimate |
| 4 | Contact 5 | draft | Yes (WS 3) | Yes (Est 2) | Direct line items test |
| 5 | Contact 2 | draft | Yes (WS 2) | Yes (Est 3) | **Bundling test**: worksheet + bundled estimate |

### 11. EstWorksheets (3 worksheets)

| PK | Job | Template | Linked Estimate | Purpose |
|----|-----|----------|-----------------|---------|
| 1 | Job 2 | 1 (Simple Service) | None | Direct tasks, no estimate yet |
| 2 | Job 5 | 2 (Cabinet Build) | Est 3 | **Bundling test**: tasks bundle into Est 3 line item |
| 3 | Job 4 | None | Est 2 | Manual worksheet for direct line items |

### 12. Estimates (3 estimates)

| PK | Job | Status | Has Line Items | Purpose |
|----|-----|--------|----------------|---------|
| 1 | Job 3 | draft | No | Empty draft estimate |
| 2 | Job 4 | draft | Yes (3 items) | Estimate with mixed direct line items |
| 3 | Job 5 | draft | Yes (5+ items) | Full test: direct + bundled line items |

### 13. EstimateLineItems (7 line items across estimates)

**Estimate 2 (Job 4) - 3 direct items:**
| PK | Type | Source | Taxable Override | Purpose |
|----|------|--------|------------------|---------|
| 1 | SVC | PriceListItem 1 | null (use default) | Service via price list |
| 2 | MAT | Task 7 | null | Material via task (direct mapping) |
| 3 | FRT | PriceListItem 5 | null | Non-taxable freight |

**Estimate 3 (Job 5) - 4 items (direct + bundled):**
| PK | Type | Source | Taxable Override | Purpose |
|----|------|--------|------------------|---------|
| 4 | SVC | Task 1 | null | Service from direct labor task |
| 5 | MAT | PriceListItem 2 | true | Material, forced taxable |
| 6 | OVH | PriceListItem 6 | null | Overhead non-taxable |
| 7 | PRD | **Bundled** (Tasks 2-4) | null | **BUNDLED**: Cabinet from component tasks |

**Note on line item 7 (bundled):**
- This line item represents the output of the bundling process
- Tasks 2, 3, 4 (Cabinet Frame, Doors, Finish) have TaskInstanceMappings with product_identifier="cabinet_001"
- ProductBundlingRule matches and creates a single PRD line item
- Price = sum of component task prices (per pricing_method='sum_components')
- Description from line_item_template: "Custom Cabinet - cabinet_001"

### 14. PurchaseOrders (2 POs)

| # | Business | Job | Status | Purpose |
|---|----------|-----|--------|---------|
| 1 | Acme Supplies | Job 4 | draft | PO with line items |
| 2 | Acme Supplies | None | draft | Standalone PO |

### 15. PurchaseOrderLineItems (3 items)

**PO 1:**
| Type | Source | Purpose |
|------|--------|---------|
| MAT | PriceListItem | Material purchase |
| FRT | PriceListItem | Shipping on PO |

**PO 2:**
| Type | Source | Purpose |
|------|--------|---------|
| MAT | PriceListItem | Standalone material order |

### 16. Bills (2 bills)

| # | Business | PO | Status | Purpose |
|---|----------|-----|--------|---------|
| 1 | Acme Supplies | PO 1 | draft | Bill linked to PO |
| 2 | Acme Supplies | None | draft | Standalone bill |

### 17. BillLineItems (3 items)

**Bill 1:**
| Type | Source | Purpose |
|------|--------|---------|
| MAT | PriceListItem | Received materials |

**Bill 2:**
| Type | Source | Purpose |
|------|--------|---------|
| MAT | PriceListItem | Direct material bill |
| OVH | PriceListItem | Overhead charge |

### 18. Tasks (8 tasks across worksheets)

**EstWorksheet 1 (Job 2) - Simple Service template, 2 tasks:**
| PK | Template | Name | est_qty | Mapping Strategy | Purpose |
|----|----------|------|---------|------------------|---------|
| 1 | 1 (Basic Labor) | "Consultation" | 4.00 | direct → SVC | Direct service line item |
| 2 | 2 (Material Handling) | "Material Setup" | 2.00 | direct → MAT | Direct material line item |

**EstWorksheet 2 (Job 5) - Cabinet Build template, 4 tasks:**
| PK | Template | Name | est_qty | Mapping Strategy | Purpose |
|----|----------|------|---------|------------------|---------|
| 3 | 3 (Cabinet Frame) | "Cabinet Frame" | 1.00 | bundle_to_product → PRD | **BUNDLE**: Frame component |
| 4 | 4 (Cabinet Doors) | "Cabinet Doors" | 2.00 | bundle_to_product → PRD | **BUNDLE**: Doors component |
| 5 | 5 (Cabinet Finish) | "Cabinet Finish" | 1.00 | bundle_to_product → PRD | **BUNDLE**: Finish component |
| 6 | 6 (Shop Overhead) | "Shop Overhead" | 2.00 | exclude | Excluded from estimate |

**EstWorksheet 3 (Job 5) - Manual worksheet, 2 tasks:**
| PK | Template | Name | est_qty | Mapping Strategy | Purpose |
|----|----------|------|---------|------------------|---------|
| 7 | 2 (Material Handling) | "Extra Materials" | 5.00 | direct → MAT | For Estimate 2 line item |
| 8 | None | "Custom Work" | 1.00 | (none) | Manual task, no mapping |

### 18a. TaskInstanceMappings (for bundling test)

These entries group tasks into products for bundling:

| task_id (PK) | product_identifier | product_instance | Purpose |
|--------------|-------------------|------------------|---------|
| 3 | "cabinet_001" | 1 | Groups frame into cabinet 1 |
| 4 | "cabinet_001" | 1 | Groups doors into cabinet 1 |
| 5 | "cabinet_001" | 1 | Groups finish into cabinet 1 |

**Bundling test scenario:**
- Tasks 3, 4, 5 all have product_identifier="cabinet_001"
- ProductBundlingRule 1 matches product_type="cabinet"
- When estimate is generated from worksheet:
  - Tasks 3, 4, 5 → bundled into 1 EstimateLineItem (type PRD)
  - Task 6 (overhead, exclude strategy) → not included
  - Price = (1×200) + (2×150) + (1×100) = $600

---

## UI Test Scenarios Enabled

### LineItemType CRUD (Settings > Line Item Types)
- View list of all 6 types
- Create new type
- Edit existing type (change taxability)
- Deactivate type (soft delete)

### Estimate Line Items - Direct
- Add line item from PriceListItem (type auto-populated)
- Add line item from Task with direct mapping (type via TaskMapping.output_line_item_type)
- Change LineItemType on line item
- Override taxable flag
- View tax calculations with mixed types

### Estimate Line Items - Bundled (known bug area)
- Create estimate from worksheet with bundled tasks
- Verify bundled tasks become single line item with correct LineItemType (PRD)
- Verify bundled line item price = sum of component task prices
- Verify excluded tasks (overhead) don't appear
- Test the current (buggy) behavior to document it
- Verify fix when implemented

### Purchase Order Line Items
- Add line item with LineItemType
- Type dropdown shows all active types
- Type affects categorization

### Bill Line Items
- Add line item with LineItemType
- Verify type persists from PO (if linked)

### Tax Calculation Display
- Estimate shows taxable/non-taxable subtotals
- Different LineItemTypes affect tax calculation
- Override flag supersedes type default
- Bundled line items inherit taxability from LineItemType

---

## File Structure

Single fixture file: `fixtures/line_item_type_test_data.json`

Load order (handled by Django):
1. auth.group
2. core.configuration
3. core.lineitemtype
4. contacts.business (partial - no default_contact yet)
5. contacts.contact
6. contacts.business (update default_contact)
7. core.user
8. invoicing.pricelistitem
9. jobs.taskmapping
10. jobs.tasktemplate
11. jobs.workordertemplate
12. jobs.templatetaskassociation
13. jobs.productbundlingrule
14. jobs.job
15. jobs.estworksheet
16. jobs.task
17. jobs.taskinstancemapping
18. jobs.estimate
19. jobs.estimatelineitem
20. purchasing.purchaseorder
21. purchasing.purchaseorderlineitem
22. purchasing.bill
23. purchasing.billlineitem

---

## Task List

### Task 1: Create LineItemType and Configuration entries

**Files:**
- Create: `fixtures/line_item_type_test_data.json`

**Step 1:** Write the fixture header and LineItemType entries (6 types)

**Step 2:** Add Configuration entries with counters starting at 100

**Step 3:** Add auth.group entries (Administrator, Manager, Employee)

---

### Task 2: Add Contacts and Businesses

**Step 1:** Add Business entries (without default_contact initially)

**Step 2:** Add Contact entries (with business references where needed)

**Step 3:** Add Users with contact references

---

### Task 3: Add PriceListItems with LineItemType references

**Step 1:** Add 7 PriceListItem entries, each referencing appropriate LineItemType

---

### Task 4: Add TaskMappings, TaskTemplates, and Bundling Rules

**Step 1:** Add TaskMapping entries with output_line_item_type (4 mappings)

**Step 2:** Add TaskTemplate entries with task_mapping references (6 templates)

**Step 3:** Add WorkOrderTemplate entries (2 templates)

**Step 4:** Add TemplateTaskAssociation entries (6 associations)

**Step 5:** Add ProductBundlingRule entries (1 rule for cabinet bundling)

---

### Task 5: Add Jobs and EstWorksheets

**Step 1:** Add 5 Job entries in draft state

**Step 2:** Add 3 EstWorksheet entries

---

### Task 6: Add Tasks and TaskInstanceMappings

**Step 1:** Add 8 Task entries across worksheets

**Step 2:** Add TaskInstanceMapping entries for bundled tasks (3 mappings for cabinet_001)

---

### Task 7: Add Estimates and EstimateLineItems

**Step 1:** Add 3 Estimate entries

**Step 2:** Add 7 EstimateLineItem entries (including 1 bundled from tasks 3-5)

---

### Task 8: Add PurchaseOrders and Bills with LineItems

**Step 1:** Add 2 PurchaseOrder entries

**Step 2:** Add 3 PurchaseOrderLineItem entries

**Step 3:** Add 2 Bill entries

**Step 4:** Add 3 BillLineItem entries

---

### Task 9: Validate the fixture loads correctly

**Step 1:** Run Django loaddata to verify fixture validity

```bash
python manage.py loaddata fixtures/line_item_type_test_data.json --verbosity 2
```

**Step 2:** Verify counts match expected:
- 6 LineItemTypes
- 3 Users
- 5 Contacts
- 2 Businesses
- 7 PriceListItems
- 4 TaskMappings
- 6 TaskTemplates
- 2 WorkOrderTemplates
- 6 TemplateTaskAssociations
- 1 ProductBundlingRule
- 5 Jobs
- 3 EstWorksheets
- 8 Tasks
- 3 TaskInstanceMappings
- 3 Estimates
- 7 EstimateLineItems
- 2 PurchaseOrders
- 3 PurchaseOrderLineItems
- 2 Bills
- 3 BillLineItems

---

## Additional Considerations

### What else might be needed?

1. **Invoices** - If testing invoice line items with LineItemTypes, add:
   - 2 Invoice entries (one per job with estimates)
   - InvoiceLineItem entries mirroring estimate line items

2. **WorkOrders** - Currently not included. Only needed if testing work order → invoice flow with LineItemTypes.

3. **PaymentTerms** - Optional, only if testing payment terms display on businesses.

4. **Bleps (time tracking)** - Not needed for LineItemType testing.

### Intentionally Excluded

- Jobs in non-draft states (approved, completed) - creates complexity without testing benefit
- Estimates in non-draft states (open, accepted) - same reason
- Multiple estimate versions - not relevant to LineItemType testing
- WorkOrders - LineItemType focus is on estimates/invoices/POs/bills

---

## Summary

This dataset provides:
- **6 LineItemTypes** with varied taxability (SVC, MAT, MFR, PRD, FRT, OVH)
- **3 Users** across permission levels
- **5 Contacts** including 2 from same business
- **2 Businesses** (vendor + customer)
- **7 PriceListItems** covering all types
- **4 TaskMappings** including bundle_to_product for testing
- **6 TaskTemplates** with varied mapping strategies
- **2 WorksheetTemplates** (service + product/bundling)
- **1 ProductBundlingRule** for cabinet bundling test
- **5 Jobs** in draft state with varying completeness
- **3 EstWorksheets** with 8 tasks total
- **3 TaskInstanceMappings** grouping cabinet components
- **3 Estimates** with 7 line items (including 1 bundled)
- **2 PurchaseOrders** with 3 line items
- **2 Bills** with 3 line items

All objects are in reachable states (draft) and properly linked, enabling comprehensive UI testing of LineItemType functionality including the bundling workflow.
