#!/bin/bash
# Seed realistic data through the API so all business logic, number generation,
# and history tracking runs naturally.
#
# AutoLoginMiddleware handles authentication automatically on every request.
# We still need a cookie jar for CSRF tokens (required by DRF SessionAuthentication).
#
# Prerequisites:
#   - Dev server running on :8000 (python manage.py runserver)
#   - dev_user exists (AutoLoginMiddleware needs it)
#   - Database has been migrated
#
# Works on a fresh (empty) database — bootstraps Configuration entries
# and Line Item Types if missing. Safe to re-run; won't overwrite
# existing counters.
#
# Usage: ./scripts/seed_data.sh

set -e

BASE="http://localhost:8000"
COOKIE_JAR="/tmp/minibini_seed_cookies.txt"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}>>> $1${NC}"; }
info() { echo -e "${BLUE}    $1${NC}"; }

# Helper: POST JSON, return response body. Returns non-zero on failure.
post() {
    local url="$1"
    local data="$2"
    local http_code response
    response=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
        -w "\n%{http_code}" \
        -X POST "$BASE$url" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $(grep csrftoken "$COOKIE_JAR" | awk '{print $NF}')" \
        -d "$data")
    http_code=$(echo "$response" | tail -1)
    response=$(echo "$response" | sed '$d')
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        echo "$response"
    else
        echo "FAILED ($http_code): POST $url" >&2
        echo "$response" >&2
        return 1
    fi
}

# Helper: PATCH JSON
patch() {
    local url="$1"
    local data="$2"
    local http_code response
    response=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
        -w "\n%{http_code}" \
        -X PATCH "$BASE$url" \
        -H "Content-Type: application/json" \
        -H "X-CSRFToken: $(grep csrftoken "$COOKIE_JAR" | awk '{print $NF}')" \
        -d "$data")
    http_code=$(echo "$response" | tail -1)
    response=$(echo "$response" | sed '$d')
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        echo "$response"
    else
        echo "FAILED ($http_code): PATCH $url" >&2
        echo "$response" >&2
        return 1
    fi
}

# Helper: extract field from JSON
jval() { python3 -c "import sys,json; print(json.load(sys.stdin)['$1'])"; }

# Helper: POST form data to HTML views (for endpoints not yet in the API).
# TODO: Replace with API calls once association endpoints are added.
form_post() {
    local url="$1"
    shift
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
        -X POST "$BASE$url" \
        -H "X-CSRFToken: $(grep csrftoken "$COOKIE_JAR" | awk '{print $NF}')" \
        "$@")
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ]; then
        return 0
    else
        echo "FAILED ($http_code): FORM POST $url" >&2
        return 1
    fi
}

# ─────────────────────────────────────────────
# Step 0: Establish session (AutoLoginMiddleware handles auth)
# ─────────────────────────────────────────────
log "Establishing session..."
rm -f "$COOKIE_JAR"
# One GET to trigger AutoLoginMiddleware and get CSRF cookie
curl -s -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE/api/jobs/" > /dev/null
info "Session established"

# ─────────────────────────────────────────────
# Step 1: Ensure Configuration entries exist
# ─────────────────────────────────────────────
log "Ensuring configuration..."
# Fetch current settings, only set missing keys
CURRENT_SETTINGS=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE/api/settings/")
needs_config() { echo "$CURRENT_SETTINGS" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if '$1' not in d else 1)"; }

PATCH_DATA="{}"
for pair in \
    'job_number_sequence:JOB-{year}-{counter:04d}' \
    'job_counter:0' \
    'estimate_number_sequence:EST-{year}-{counter:04d}' \
    'estimate_counter:0' \
    'invoice_number_sequence:INV-{year}-{counter:04d}' \
    'invoice_counter:0' \
    'po_number_sequence:PO-{year}-{counter:04d}' \
    'po_counter:0' \
    'bill_number_sequence:BILL-{year}-{counter:04d}' \
    'bill_counter:0'; do
    key="${pair%%:*}"
    val="${pair#*:}"
    if needs_config "$key"; then
        PATCH_DATA=$(echo "$PATCH_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); d['$key']='$val'; print(json.dumps(d))")
    fi
done

if [ "$PATCH_DATA" != "{}" ]; then
    patch "/api/settings/" "$PATCH_DATA" > /dev/null
    info "Missing configuration keys added"
else
    info "Configuration already present"
fi

# ─────────────────────────────────────────────
# Step 2: Line Item Types (skip if they already exist) (skip if they already exist)
# ─────────────────────────────────────────────
log "Ensuring Line Item Types exist..."
post "/api/line-item-types/" '{"code":"SVC","name":"Service","taxable":false,"default_description":"Professional services and labor"}' > /dev/null 2>&1 || true
post "/api/line-item-types/" '{"code":"MTL","name":"Material","taxable":true,"default_description":"Raw materials"}' > /dev/null 2>&1 || true
post "/api/line-item-types/" '{"code":"PRD","name":"Product","taxable":true,"default_description":"Finished products"}' > /dev/null 2>&1 || true
post "/api/line-item-types/" '{"code":"DLV","name":"Delivery","taxable":false,"default_description":"Shipping and delivery"}' > /dev/null 2>&1 || true
info "Line item types OK"

# Look up LIT IDs by code for use in templates and price list items
LIT_JSON=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE/api/line-item-types/")
lit_id() { echo "$LIT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); items=d.get('results',d) if isinstance(d,dict) else d; print(next(x['id'] for x in items if x['code']=='$1'))"; }
LIT_SVC=$(lit_id "SVC")
LIT_MTL=$(lit_id "MTL")
LIT_PRD=$(lit_id "PRD")
LIT_DLV=$(lit_id "DLV")
info "LIT IDs: SVC=$LIT_SVC MTL=$LIT_MTL PRD=$LIT_PRD DLV=$LIT_DLV"

# ─────────────────────────────────────────────
# Step 2b: Price List Items
# ─────────────────────────────────────────────
log "Creating Price List Items..."
post "/api/price-list-items/" '{"code":"LAB001","units":"hour","description":"General Labor - per hour","purchase_price":"25.00","selling_price":"45.00","is_inventoried":false,"line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/price-list-items/" '{"code":"LAB002","units":"hour","description":"Skilled Labor - per hour","purchase_price":"45.00","selling_price":"85.00","is_inventoried":false,"line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/price-list-items/" '{"code":"BBPLY.75","units":"sheets","description":"4x8 x 3/4 in Baltic Birch plywood","purchase_price":"98.00","selling_price":"98.00","is_inventoried":true,"line_item_type":'"$LIT_MTL"'}' > /dev/null
post "/api/price-list-items/" '{"code":"WOAK.75","units":"sheets","description":"4x8 x 3/4 in rift sawn white oak veneer plywood","purchase_price":"185.00","selling_price":"185.00","is_inventoried":true,"line_item_type":'"$LIT_MTL"'}' > /dev/null
post "/api/price-list-items/" '{"code":"MDF.75","units":"sheets","description":"4x8 x 3/4 in MDF","purchase_price":"42.00","selling_price":"42.00","is_inventoried":true,"line_item_type":'"$LIT_MTL"'}' > /dev/null
info "5 price list items created (3 inventoried)"

# ─────────────────────────────────────────────
# Step 2c: Task Templates
# ─────────────────────────────────────────────
log "Creating Task Templates..."
TT_RESEARCH=$(post "/api/task-templates/" '{"template_name":"RESEARCH","description":"Research before project can be started","units":"hours","rate":"100.00","line_item_type":'"$LIT_SVC"'}' | jval "template_id")
TT_CAD=$(post "/api/task-templates/" '{"template_name":"CAD","description":"Design, drawing, detailing, modelling","units":"hours","rate":"150.00","line_item_type":'"$LIT_SVC"'}' | jval "template_id")
TT_CUT=$(post "/api/task-templates/" '{"template_name":"CUT","description":"Cutting parts","units":"minutes","rate":"22.00","line_item_type":'"$LIT_PRD"'}' | jval "template_id")
TT_ASSEMBLE=$(post "/api/task-templates/" '{"template_name":"ASSEMBLE","description":"Glue and staple the parts together","units":"hours","rate":"100.00","line_item_type":'"$LIT_PRD"'}' | jval "template_id")
TT_FINISH=$(post "/api/task-templates/" '{"template_name":"FINISH","description":"Sand, fill, apply finish or veneer or laminate","units":"hours","rate":"100.00","line_item_type":'"$LIT_PRD"'}' | jval "template_id")
TT_PALLET=$(post "/api/task-templates/" '{"template_name":"PALLET","description":"Palletize piece, build or customize a pallet if needed","units":"hours","rate":"100.00","line_item_type":'"$LIT_SVC"'}' | jval "template_id")
TT_SITEVISIT=$(post "/api/task-templates/" '{"template_name":"SITE VISIT","description":"Go to customer location to evaluate and measure","units":"hours","rate":"200.00","line_item_type":'"$LIT_SVC"'}' | jval "template_id")
TT_JIG=$(post "/api/task-templates/" '{"template_name":"JIG","description":"Design and build jig(s) for assembly. ADD JIG MATERIAL SEPARATELY","units":"hours","rate":"150.00","line_item_type":'"$LIT_PRD"'}' | jval "template_id")
TT_DELIVERY=$(post "/api/task-templates/" '{"template_name":"DELIVERY","description":"Deliver in our truck or arrange external delivery","units":"-","rate":"150.00","line_item_type":'"$LIT_DLV"'}' | jval "template_id")
info "9 task templates created"

# ─────────────────────────────────────────────
# Step 2d: Work Order Templates + Associations
# ─────────────────────────────────────────────
log "Creating Work Order Templates..."
WOT_TABLE=$(post "/api/work-order-templates/" '{"template_name":"Table","description":"Template for building a custom table"}' | jval "template_id")
WOT_SIGN=$(post "/api/work-order-templates/" '{"template_name":"SIGN","description":"Template for a custom sign, installed"}' | jval "template_id")
info "2 work order templates created"

# TODO: Replace these HTML form POSTs with API calls once an association
# endpoint is added to the work-order-templates API.
log "Associating task templates (via HTML views)..."

# Table: CAD(10h) → CUT(125min) → ASSEMBLE(3h) → FINISH(12h)
form_post "/estimates/templates/$WOT_TABLE/" -d "associate_task=1" -d "task_template_id=$TT_CAD" -d "est_qty=10.00"
form_post "/estimates/templates/$WOT_TABLE/" -d "associate_task=1" -d "task_template_id=$TT_CUT" -d "est_qty=125.00"
form_post "/estimates/templates/$WOT_TABLE/" -d "associate_task=1" -d "task_template_id=$TT_ASSEMBLE" -d "est_qty=3.00"
form_post "/estimates/templates/$WOT_TABLE/" -d "associate_task=1" -d "task_template_id=$TT_FINISH" -d "est_qty=12.00"
info "Table template: 4 task associations"

# SIGN: SITE VISIT(1h) → CAD(3h) → CUT(85min) → FINISH(5h)
form_post "/estimates/templates/$WOT_SIGN/" -d "associate_task=1" -d "task_template_id=$TT_SITEVISIT" -d "est_qty=1.00"
form_post "/estimates/templates/$WOT_SIGN/" -d "associate_task=1" -d "task_template_id=$TT_CAD" -d "est_qty=3.00"
form_post "/estimates/templates/$WOT_SIGN/" -d "associate_task=1" -d "task_template_id=$TT_CUT" -d "est_qty=85.00"
form_post "/estimates/templates/$WOT_SIGN/" -d "associate_task=1" -d "task_template_id=$TT_FINISH" -d "est_qty=5.00"
info "SIGN template: 4 task associations"

# ─────────────────────────────────────────────
# Step 3: Create primary contact (without business yet)
# ─────────────────────────────────────────────
log "Creating Contacts..."
CONTACT1_RESP=$(post "/api/contacts/" '{
    "first_name": "Sarah",
    "last_name": "Chen",
    "email": "schen@meridianarch.example.com",
    "work_number": "503-555-0181",
    "mobile_number": "503-555-0199",
    "addr1": "450 Design Center Dr",
    "addr2": "Suite 200",
    "city": "Portland",
    "municipality": "OR",
    "postal_code": "97205",
    "country_code": "US"
}')
CONTACT1_ID=$(echo "$CONTACT1_RESP" | jval "contact_id")
info "Contact: Sarah Chen (id=$CONTACT1_ID)"

# ─────────────────────────────────────────────
# Step 4: Business (with Sarah as default contact)
# ─────────────────────────────────────────────
log "Creating Business..."
BIZ_RESP=$(post "/api/businesses/" '{
    "business_name": "Meridian Architecture Group",
    "business_address": "450 Design Center Dr, Suite 200, Portland OR 97205",
    "business_phone": "503-555-0180",
    "website": "https://meridianarch.example.com",
    "default_contact_id": '"$CONTACT1_ID"'
}')
BIZ_ID=$(echo "$BIZ_RESP" | jval "business_id")
info "Business: Meridian Architecture Group (id=$BIZ_ID)"

# Second contact at the business
CONTACT2_RESP=$(post "/api/contacts/" '{
    "first_name": "Marcus",
    "last_name": "Rivera",
    "email": "mrivera@meridianarch.example.com",
    "work_number": "503-555-0182",
    "addr1": "450 Design Center Dr",
    "addr2": "Suite 200",
    "city": "Portland",
    "municipality": "OR",
    "postal_code": "97205",
    "country_code": "US",
    "business_id": '"$BIZ_ID"'
}')
CONTACT2_ID=$(echo "$CONTACT2_RESP" | jval "contact_id")
info "Contact: Marcus Rivera (id=$CONTACT2_ID)"

# ─────────────────────────────────────────────
# Step 5: Job
# ─────────────────────────────────────────────
log "Creating Job..."
JOB_RESP=$(post "/api/jobs/" '{
    "name": "Custom reception desk with integrated lighting",
    "contact": '"$CONTACT1_ID"',
    "customer_po_number": "MAG-2026-0042",
    "description": "Custom curved reception desk in white oak with LED strip lighting integrated into the front panel. Dimensions: 8ft wide, 42in high, 30in deep. Includes cable management and power outlets."
}')
JOB_ID=$(echo "$JOB_RESP" | jval "job_id")
JOB_NUM=$(echo "$JOB_RESP" | jval "job_number")
info "Job: $JOB_NUM (id=$JOB_ID)"

# Add a note about initial client meeting
post "/api/jobs/$JOB_ID/notes/" '{"text":"Initial meeting with Sarah Chen. She showed photos of a similar desk they saw at a hotel in Tokyo. Wants warm wood tones with subtle lighting. Budget discussed around $12-15k."}' > /dev/null
info "Added note about client meeting"

# ─────────────────────────────────────────────
# Step 6: Estimate Worksheet (with tasks)
# ─────────────────────────────────────────────
log "Creating Estimate Worksheet..."
WS_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB_ID"'}')
WS_ID=$(echo "$WS_RESP" | jval "est_worksheet_id")
info "Worksheet created (id=$WS_ID)"

log "Adding tasks to worksheet..."
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"Design & drafting","description":"CAD drawings and material selection","units":"hours","rate":"100.00","est_qty":"12","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"Material procurement","description":"Source white oak lumber, LED strips, power components","units":"lot","rate":"1.00","est_qty":"1","line_item_type":'"$LIT_MTL"'}' > /dev/null
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"Milling & shaping","description":"Mill lumber to dimension, shape curved front panel","units":"hours","rate":"85.00","est_qty":"16","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"Joinery & assembly","description":"Mortise and tenon joints, assemble desk frame and panels","units":"hours","rate":"85.00","est_qty":"20","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"LED integration","description":"Route channels, install LED strips and drivers, wire to power","units":"hours","rate":"75.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"Finishing","description":"Sand, seal, and apply finish coats","units":"hours","rate":"70.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS_ID/tasks/" '{"name":"Delivery & installation","description":"Transport to site and install","units":"hours","rate":"85.00","est_qty":"4","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "7 tasks added"

# ─────────────────────────────────────────────
# Step 7: Generate Estimate from Worksheet
# ─────────────────────────────────────────────
log "Generating Estimate from Worksheet..."
EST_GEN_RESP=$(post "/api/est-worksheets/$WS_ID/generate-estimate/")
EST_ID=$(echo "$EST_GEN_RESP" | jval "estimate_id")
EST_NUM=$(echo "$EST_GEN_RESP" | jval "estimate_number")
info "Estimate: $EST_NUM (id=$EST_ID)"

# Add a note about pricing
post "/api/jobs/$JOB_ID/notes/" '{"text":"Estimate generated. Material costs came in higher than expected due to white oak prices. May need to discuss with Sarah if total exceeds budget."}' > /dev/null
info "Added note about pricing"

# ─────────────────────────────────────────────
# Step 8: Mark Estimate as Open (sent to client)
# ─────────────────────────────────────────────
log "Marking Estimate as Open (sent to client)..."
post "/api/estimates/$EST_ID/mark-open/" '{}' > /dev/null
info "Estimate marked as open"

# ─────────────────────────────────────────────
# Step 9: Client accepts estimate
# ─────────────────────────────────────────────
log "Client accepts estimate..."
# Accept the estimate — this triggers job approval via signal
patch "/api/estimates/$EST_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate accepted (job should now be approved)"

post "/api/jobs/$JOB_ID/notes/" '{"text":"Sarah confirmed acceptance by email. She chose the satin finish over the gloss option. Start date agreed: next Monday."}' > /dev/null
info "Added acceptance note"

# ─────────────────────────────────────────────
# Step 10: Create Work Order
# ─────────────────────────────────────────────
log "Creating Work Order..."
WO_RESP=$(post "/api/work-orders/" '{"job": '"$JOB_ID"'}')
WO_ID=$(echo "$WO_RESP" | jval "work_order_id")
info "Work Order created (id=$WO_ID)"

log "Adding tasks to work order..."
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Design & drafting","description":"Final CAD drawings","units":"hours","rate":"100.00","est_qty":"12","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Mill white oak lumber","description":"Mill all pieces to dimension","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Shape curved front panel","description":"Steam bend and shape the curved panel","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Cut joinery","description":"Mortise and tenon joints for frame","units":"hours","rate":"85.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Assemble desk","description":"Dry fit, glue, and clamp","units":"hours","rate":"85.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Route LED channels","description":"Route channels in front panel for LED strips","units":"hours","rate":"75.00","est_qty":"4","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Install electrical","description":"LED strips, drivers, wiring, outlets","units":"hours","rate":"75.00","est_qty":"4","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Sand & finish","description":"Progressive sanding and 3 coats satin finish","units":"hours","rate":"70.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO_ID/tasks/" '{"name":"Deliver & install","description":"Transport to site and final installation","units":"hours","rate":"85.00","est_qty":"4","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "9 tasks added to work order"

# ─────────────────────────────────────────────
# Step 11: Create Invoice
# ─────────────────────────────────────────────
log "Creating Invoice..."
INV_RESP=$(post "/api/invoices/" '{"job": '"$JOB_ID"'}')
INV_ID=$(echo "$INV_RESP" | jval "invoice_id")
INV_NUM=$(echo "$INV_RESP" | jval "invoice_number")
info "Invoice: $INV_NUM (id=$INV_ID)"

log "Adding line items to invoice..."
post "/api/invoices/$INV_ID/line-items/" '{"description":"Design & drafting - custom reception desk","qty":"12","units":"hours","price":"100.00"}' > /dev/null
post "/api/invoices/$INV_ID/line-items/" '{"description":"White oak lumber, select grade","qty":"1","units":"lot","price":"2800.00"}' > /dev/null
post "/api/invoices/$INV_ID/line-items/" '{"description":"LED strip lighting kit & drivers","qty":"1","units":"kit","price":"450.00"}' > /dev/null
post "/api/invoices/$INV_ID/line-items/" '{"description":"Fabrication - milling, shaping, joinery","qty":"36","units":"hours","price":"85.00"}' > /dev/null
post "/api/invoices/$INV_ID/line-items/" '{"description":"Electrical integration","qty":"8","units":"hours","price":"75.00"}' > /dev/null
post "/api/invoices/$INV_ID/line-items/" '{"description":"Finishing - sanding & satin coat","qty":"10","units":"hours","price":"70.00"}' > /dev/null
post "/api/invoices/$INV_ID/line-items/" '{"description":"Delivery & on-site installation","qty":"4","units":"hours","price":"85.00"}' > /dev/null
info "7 line items added to invoice"

# ─────────────────────────────────────────────
# Step 12: Add a few more notes
# ─────────────────────────────────────────────
log "Adding final notes..."
post "/api/contacts/$CONTACT1_ID/notes/" '{"text":"Sarah prefers email over phone. Best reached before 10am."}' > /dev/null
info "Added note to contact"

post "/api/businesses/$BIZ_ID/notes/" '{"text":"Meridian has done 3 projects with us previously. Good payment history. Marcus handles AP."}' > /dev/null
info "Added note to business"

post "/api/jobs/$JOB_ID/notes/" '{"text":"White oak shipment arrived, checking for defects before milling."}' > /dev/null
info "Added note about materials"

# ═══════════════════════════════════════════════
# SCENARIO 2: Solo contact — sign job, cancelled
# ═══════════════════════════════════════════════

log "Creating solo contact (Derek Lam)..."
CONTACT3_RESP=$(post "/api/contacts/" '{
    "first_name": "Derek",
    "last_name": "Lam",
    "email": "derek.lam@example.com",
    "mobile_number": "415-555-0230",
    "addr1": "88 Valencia St",
    "city": "San Francisco",
    "municipality": "CA",
    "postal_code": "94103",
    "country_code": "US"
}')
CONTACT3_ID=$(echo "$CONTACT3_RESP" | jval "contact_id")
info "Contact: Derek Lam (id=$CONTACT3_ID) — no business"

log "Creating sign job for Derek..."
JOB2_RESP=$(post "/api/jobs/" '{
    "name": "Custom exterior sign for coffee shop",
    "contact": '"$CONTACT3_ID"',
    "description": "Carved HDU sign, 4ft x 2ft, double-sided with bracket mount. Gold leaf lettering on dark green background."
}')
JOB2_ID=$(echo "$JOB2_RESP" | jval "job_id")
JOB2_NUM=$(echo "$JOB2_RESP" | jval "job_number")
info "Job: $JOB2_NUM (id=$JOB2_ID)"

post "/api/jobs/$JOB2_ID/notes/" '{"text":"Derek wants something old-fashioned looking. Showed reference photos of signs in North Beach."}' > /dev/null

log "Creating worksheet with sign tasks..."
WS2_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB2_ID"'}')
WS2_ID=$(echo "$WS2_RESP" | jval "est_worksheet_id")
# Tasks matching the SIGN template associations
post "/api/est-worksheets/$WS2_ID/tasks/" '{"name":"SITE VISIT","description":"Go to customer location to evaluate and measure","units":"hours","rate":"200.00","est_qty":"1","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS2_ID/tasks/" '{"name":"CAD","description":"Design, drawing, detailing, modelling","units":"hours","rate":"150.00","est_qty":"3","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS2_ID/tasks/" '{"name":"CUT","description":"Cutting parts","units":"minutes","rate":"22.00","est_qty":"85","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS2_ID/tasks/" '{"name":"FINISH","description":"Sand, fill, apply finish or veneer or laminate","units":"hours","rate":"100.00","est_qty":"5","line_item_type":'"$LIT_PRD"'}' > /dev/null
info "Worksheet created with 4 tasks (id=$WS2_ID)"

log "Generating estimate, marking open, accepting..."
EST2_GEN_RESP=$(post "/api/est-worksheets/$WS2_ID/generate-estimate/")
EST2_ID=$(echo "$EST2_GEN_RESP" | jval "estimate_id")
EST2_NUM=$(echo "$EST2_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST2_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST2_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST2_NUM accepted (job approved)"

log "Cancelling job — no deposit received..."
post "/api/jobs/$JOB2_ID/cancel/" '{"reason":"Client did not pay deposit within 30 days. Attempted follow-up calls on 3/1 and 3/7 with no response."}' > /dev/null
post "/api/jobs/$JOB2_ID/notes/" '{"text":"Tried calling Derek twice, no answer. Sent final email giving 7 more days. No response. Cancelling."}' > /dev/null
info "Job $JOB2_NUM cancelled"

# ═══════════════════════════════════════════════
# SCENARIO 3: Two contacts at same business — two jobs
# ═══════════════════════════════════════════════

log "Creating contacts at Bayside Brewing..."

CONTACT4_RESP=$(post "/api/contacts/" '{
    "first_name": "Tomoko",
    "last_name": "Sato",
    "email": "tsato@baysidebrewing.example.com",
    "work_number": "510-555-0310",
    "mobile_number": "510-555-0319",
    "addr1": "2200 Maritime St",
    "city": "Oakland",
    "municipality": "CA",
    "postal_code": "94607",
    "country_code": "US"
}')
CONTACT4_ID=$(echo "$CONTACT4_RESP" | jval "contact_id")
info "Contact: Tomoko Sato (id=$CONTACT4_ID)"

BIZ2_RESP=$(post "/api/businesses/" '{
    "business_name": "Bayside Brewing Co",
    "business_address": "2200 Maritime St, Oakland CA 94607",
    "business_phone": "510-555-0300",
    "website": "https://baysidebrewing.example.com",
    "default_contact_id": '"$CONTACT4_ID"'
}')
BIZ2_ID=$(echo "$BIZ2_RESP" | jval "business_id")
info "Business: Bayside Brewing Co (id=$BIZ2_ID)"

CONTACT5_RESP=$(post "/api/contacts/" '{
    "first_name": "Ray",
    "last_name": "Dominguez",
    "email": "rdominguez@baysidebrewing.example.com",
    "work_number": "510-555-0311",
    "addr1": "2200 Maritime St",
    "city": "Oakland",
    "municipality": "CA",
    "postal_code": "94607",
    "country_code": "US",
    "business_id": '"$BIZ2_ID"'
}')
CONTACT5_ID=$(echo "$CONTACT5_RESP" | jval "contact_id")
info "Contact: Ray Dominguez (id=$CONTACT5_ID)"

# --- Job 3: Completed cutting job (Tomoko) ---
log "Creating completed cutting job..."
JOB3_RESP=$(post "/api/jobs/" '{
    "name": "Cut 3 aluminum sign blanks",
    "contact": '"$CONTACT4_ID"',
    "customer_po_number": "BB-2026-008",
    "description": "Cut 3 custom shapes from 1/8 in aluminum sheet for tap handle signs. Templates provided by customer."
}')
JOB3_ID=$(echo "$JOB3_RESP" | jval "job_id")
JOB3_NUM=$(echo "$JOB3_RESP" | jval "job_number")
info "Job: $JOB3_NUM (id=$JOB3_ID)"

# Worksheet with manual tasks (simple cutting job, no template)
WS3_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB3_ID"'}')
WS3_ID=$(echo "$WS3_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS3_ID/tasks/" '{"name":"CNC setup","description":"Program and set up CNC for 3 shapes","units":"hours","rate":"150.00","est_qty":"1","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS3_ID/tasks/" '{"name":"Cut aluminum","description":"Cut 3 shapes from 1/8 in aluminum sheet","units":"minutes","rate":"22.00","est_qty":"45","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS3_ID/tasks/" '{"name":"Deburr and finish edges","description":"File and sand cut edges smooth","units":"hours","rate":"85.00","est_qty":"1","line_item_type":'"$LIT_PRD"'}' > /dev/null
info "Worksheet with 3 tasks"

# Estimate → open → accepted
EST3_GEN_RESP=$(post "/api/est-worksheets/$WS3_ID/generate-estimate/")
EST3_ID=$(echo "$EST3_GEN_RESP" | jval "estimate_id")
EST3_NUM=$(echo "$EST3_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST3_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST3_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST3_NUM accepted"

# Work order with same tasks, then complete
WO3_RESP=$(post "/api/work-orders/" '{"job": '"$JOB3_ID"'}')
WO3_ID=$(echo "$WO3_RESP" | jval "work_order_id")
post "/api/work-orders/$WO3_ID/tasks/" '{"name":"CNC setup","description":"Program and set up CNC for 3 shapes","units":"hours","rate":"150.00","est_qty":"1","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO3_ID/tasks/" '{"name":"Cut aluminum","description":"Cut 3 shapes from 1/8 in aluminum sheet","units":"minutes","rate":"22.00","est_qty":"45","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO3_ID/tasks/" '{"name":"Deburr and finish edges","description":"File and sand cut edges smooth","units":"hours","rate":"85.00","est_qty":"1","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO3_ID/complete/" '{}' > /dev/null
info "Work order completed"

# Invoice and complete the job
INV3_RESP=$(post "/api/invoices/" '{"job": '"$JOB3_ID"'}')
INV3_ID=$(echo "$INV3_RESP" | jval "invoice_id")
INV3_NUM=$(echo "$INV3_RESP" | jval "invoice_number")
post "/api/invoices/$INV3_ID/line-items/" '{"description":"CNC setup and programming","qty":"1","units":"hours","price":"150.00"}' > /dev/null
post "/api/invoices/$INV3_ID/line-items/" '{"description":"Cut 3 aluminum shapes","qty":"45","units":"minutes","price":"22.00"}' > /dev/null
post "/api/invoices/$INV3_ID/line-items/" '{"description":"Deburr and finish edges","qty":"1","units":"hours","price":"85.00"}' > /dev/null
info "Invoice $INV3_NUM created"

post "/api/jobs/$JOB3_ID/complete/" '{}' > /dev/null
post "/api/jobs/$JOB3_ID/notes/" '{"text":"Tomoko picked up the pieces. She was happy with the cuts, may have more work coming."}' > /dev/null
info "Job $JOB3_NUM completed"

# --- Job 4: Draft job (Ray) ---
log "Creating draft job..."
JOB4_RESP=$(post "/api/jobs/" '{
    "name": "Taproom menu board with changeable panels",
    "contact": '"$CONTACT5_ID"',
    "description": "Large wall-mounted menu board, 6ft x 4ft, with removable panel inserts for seasonal beer listings. Baltic birch frame with chalkboard panels."
}')
JOB4_ID=$(echo "$JOB4_RESP" | jval "job_id")
JOB4_NUM=$(echo "$JOB4_RESP" | jval "job_number")
post "/api/jobs/$JOB4_ID/notes/" '{"text":"Ray dropped off rough sketches. Wants to be able to swap out panels when they change the tap list. Needs to survive a humid taproom."}' > /dev/null
info "Job: $JOB4_NUM (id=$JOB4_ID) — draft, no work yet"

post "/api/businesses/$BIZ2_ID/notes/" '{"text":"Good local client. Tomoko handles project decisions, Ray handles facilities and logistics."}' > /dev/null
info "Added note to Bayside Brewing"

# ─────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────
echo ""
log "Seed data created successfully!"
echo ""
echo "  === Scenario 1: Meridian Architecture Group ==="
echo "  Business:  Meridian Architecture Group (id=$BIZ_ID)"
echo "  Contacts:  Sarah Chen (id=$CONTACT1_ID), Marcus Rivera (id=$CONTACT2_ID)"
echo "  Job:       $JOB_NUM (id=$JOB_ID) — approved, in progress"
echo "  Estimate:  $EST_NUM — accepted"
echo "  WorkOrder: id=$WO_ID"
echo "  Invoice:   $INV_NUM"
echo ""
echo "  === Scenario 2: Solo contact ==="
echo "  Contact:   Derek Lam (id=$CONTACT3_ID) — no business"
echo "  Job:       $JOB2_NUM (id=$JOB2_ID) — cancelled (no deposit)"
echo "  Estimate:  $EST2_NUM — accepted then job cancelled"
echo ""
echo "  === Scenario 3: Bayside Brewing Co ==="
echo "  Business:  Bayside Brewing Co (id=$BIZ2_ID)"
echo "  Contacts:  Tomoko Sato (id=$CONTACT4_ID), Ray Dominguez (id=$CONTACT5_ID)"
echo "  Job:       $JOB3_NUM (id=$JOB3_ID) — completed"
echo "  Job:       $JOB4_NUM (id=$JOB4_ID) — draft"
echo ""

rm -f "$COOKIE_JAR"
