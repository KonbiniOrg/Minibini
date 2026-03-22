#!/bin/bash
# Seed realistic data through the API so all business logic, number generation,
# and history tracking runs naturally.
#
# Logs in as dev_user via the API, then seeds data through API endpoints
# so all business logic, number generation, and history tracking runs naturally.
#
# Prerequisites:
#   - Dev server running on :8000 (python manage.py runserver)
#   - dev_user exists with password 'dev_password'
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

# Helper: get task IDs from a work order as a space-separated list
get_wo_task_ids() {
    local wo_id="$1"
    curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE/api/work-orders/$wo_id/tasks/" \
        | python3 -c "import sys,json; [print(t['task_id']) for t in json.load(sys.stdin)]"
}

# Helper: start and complete all tasks on a work order (auto-completes WO)
complete_all_tasks() {
    local wo_id="$1"
    for tid in $(get_wo_task_ids "$wo_id"); do
        post "/api/work-orders/$wo_id/tasks/$tid/start/" '{}' > /dev/null
        post "/api/work-orders/$wo_id/tasks/$tid/complete/" '{}' > /dev/null
    done
}

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
# Step 0: Log in as dev_user
# ─────────────────────────────────────────────
log "Logging in as dev_user..."
rm -f "$COOKIE_JAR"
login_response=$(curl -s -w "\n%{http_code}" -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -X POST "$BASE/api/auth/login/" \
    -H "Content-Type: application/json" \
    -d '{"username": "dev_user", "password": "dev_password"}')
login_code=$(echo "$login_response" | tail -1)
if [ "$login_code" -ne 200 ]; then
    echo "Login failed ($login_code). Is dev_user created with password 'dev_password'?" >&2
    exit 1
fi
info "Logged in"

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
complete_all_tasks "$WO3_ID"
info "All tasks started+completed (WO auto-completed)"

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

# ═══════════════════════════════════════════════
# SCENARIO 4: Cascade Event Rentals — 3 jobs at various stages
# ═══════════════════════════════════════════════

log "Creating contacts at Cascade Event Rentals..."

CONTACT6_RESP=$(post "/api/contacts/" '{
    "first_name": "Priya",
    "last_name": "Sharma",
    "email": "psharma@cascaderentals.example.com",
    "work_number": "503-555-0420",
    "mobile_number": "503-555-0429",
    "addr1": "1800 NW Industrial Way",
    "city": "Portland",
    "municipality": "OR",
    "postal_code": "97209",
    "country_code": "US"
}')
CONTACT6_ID=$(echo "$CONTACT6_RESP" | jval "contact_id")
info "Contact: Priya Sharma (id=$CONTACT6_ID)"

BIZ3_RESP=$(post "/api/businesses/" '{
    "business_name": "Cascade Event Rentals",
    "business_address": "1800 NW Industrial Way, Portland OR 97209",
    "business_phone": "503-555-0400",
    "website": "https://cascaderentals.example.com",
    "default_contact_id": '"$CONTACT6_ID"'
}')
BIZ3_ID=$(echo "$BIZ3_RESP" | jval "business_id")
info "Business: Cascade Event Rentals (id=$BIZ3_ID)"

CONTACT7_RESP=$(post "/api/contacts/" '{
    "first_name": "Ben",
    "last_name": "Nakamura",
    "email": "bnakamura@cascaderentals.example.com",
    "work_number": "503-555-0421",
    "addr1": "1800 NW Industrial Way",
    "city": "Portland",
    "municipality": "OR",
    "postal_code": "97209",
    "country_code": "US",
    "business_id": '"$BIZ3_ID"'
}')
CONTACT7_ID=$(echo "$CONTACT7_RESP" | jval "contact_id")
info "Contact: Ben Nakamura (id=$CONTACT7_ID)"

post "/api/businesses/$BIZ3_ID/notes/" '{"text":"Event rental company. Priya manages client projects, Ben runs the warehouse. They rent furniture and decor for weddings and corporate events."}' > /dev/null

# --- Job 5: DRAFT — worksheet + estimate, nothing sent yet ---
log "Creating draft job with worksheet and estimate (Ben)..."
JOB5_RESP=$(post "/api/jobs/" '{
    "name": "Storage rack system for rental inventory",
    "contact": '"$CONTACT7_ID"',
    "description": "Heavy-duty wooden storage racks for warehouse. 4 units, each 8ft tall x 6ft wide x 3ft deep, with adjustable shelf heights. Must hold stacked chairs and folding tables."
}')
JOB5_ID=$(echo "$JOB5_RESP" | jval "job_id")
JOB5_NUM=$(echo "$JOB5_RESP" | jval "job_number")
info "Job: $JOB5_NUM (id=$JOB5_ID) — draft"

post "/api/jobs/$JOB5_ID/notes/" '{"text":"Ben wants these ASAP but budget is tight. Discussed using construction-grade lumber to keep costs down. Needs to hold 500lbs per shelf."}' > /dev/null

WS5_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB5_ID"'}')
WS5_ID=$(echo "$WS5_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS5_ID/tasks/" '{"name":"Design","description":"Layout and cut list for 4 rack units","units":"hours","rate":"100.00","est_qty":"4","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS5_ID/tasks/" '{"name":"Cut lumber","description":"Cut all framing and shelf pieces","units":"hours","rate":"85.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS5_ID/tasks/" '{"name":"Assemble racks","description":"Assemble 4 rack units with lag bolts","units":"hours","rate":"85.00","est_qty":"12","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS5_ID/tasks/" '{"name":"Delivery","description":"Deliver to warehouse and position","units":"hours","rate":"85.00","est_qty":"2","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Worksheet with 4 tasks"

EST5_GEN_RESP=$(post "/api/est-worksheets/$WS5_ID/generate-estimate/")
EST5_ID=$(echo "$EST5_GEN_RESP" | jval "estimate_id")
EST5_NUM=$(echo "$EST5_GEN_RESP" | jval "estimate_number")
info "Estimate $EST5_NUM generated (still draft) — job $JOB5_NUM stays draft"

# --- Job 6: SUBMITTED — estimate sent, worksheet frozen ---
log "Creating submitted job with sent estimate (Priya)..."
JOB6_RESP=$(post "/api/jobs/" '{
    "name": "Portable bar units (set of 4)",
    "contact": '"$CONTACT6_ID"',
    "customer_po_number": "CER-2026-031",
    "description": "4 portable bar units for event rental fleet. Each 5ft wide, 42in high, fold-flat for transport. Plywood construction with laminate top and brass foot rail."
}')
JOB6_ID=$(echo "$JOB6_RESP" | jval "job_id")
JOB6_NUM=$(echo "$JOB6_RESP" | jval "job_number")
info "Job: $JOB6_NUM (id=$JOB6_ID)"

post "/api/jobs/$JOB6_ID/notes/" '{"text":"Priya needs these before wedding season starts in June. Wants them to look upscale but be durable enough for weekly rentals. Showed photos of bars at a recent gala."}' > /dev/null

WS6_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB6_ID"'}')
WS6_ID=$(echo "$WS6_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS6_ID/tasks/" '{"name":"Design & prototyping","description":"Design fold-flat mechanism, build one prototype","units":"hours","rate":"150.00","est_qty":"8","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS6_ID/tasks/" '{"name":"CNC cutting","description":"Cut plywood panels for 4 units","units":"hours","rate":"85.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS6_ID/tasks/" '{"name":"Edge banding & laminate","description":"Apply edge banding and laminate tops","units":"hours","rate":"75.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS6_ID/tasks/" '{"name":"Hardware & assembly","description":"Install hinges, latches, foot rails, assemble","units":"hours","rate":"85.00","est_qty":"12","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS6_ID/tasks/" '{"name":"Finishing","description":"Seal and clear coat all surfaces","units":"hours","rate":"70.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
info "Worksheet with 5 tasks"

EST6_GEN_RESP=$(post "/api/est-worksheets/$WS6_ID/generate-estimate/")
EST6_ID=$(echo "$EST6_GEN_RESP" | jval "estimate_id")
EST6_NUM=$(echo "$EST6_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST6_ID/mark-open/" '{}' > /dev/null
info "Estimate $EST6_NUM sent (open) — worksheet frozen"

# Manually move job to submitted since estimate being sent doesn't auto-transition
patch "/api/jobs/$JOB6_ID/" '{"status":"submitted"}' > /dev/null
info "Job $JOB6_NUM marked submitted"

# --- Job 7: APPROVED (in progress), WO incomplete, no deposit invoice ---
log "Creating in-progress job with WO, some work done (Priya)..."
JOB7_RESP=$(post "/api/jobs/" '{
    "name": "10 folding display easels",
    "contact": '"$CONTACT6_ID"',
    "customer_po_number": "CER-2026-027",
    "description": "10 large folding easels for displaying seating charts and signage at events. 5ft tall, adjustable tilt, fold flat. Oak with satin finish."
}')
JOB7_ID=$(echo "$JOB7_RESP" | jval "job_id")
JOB7_NUM=$(echo "$JOB7_RESP" | jval "job_number")
info "Job: $JOB7_NUM (id=$JOB7_ID)"

post "/api/jobs/$JOB7_ID/notes/" '{"text":"Priya ordered 10 to start. If clients like them she will order 20 more. Needs a sample by end of month."}' > /dev/null

WS7_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB7_ID"'}')
WS7_ID=$(echo "$WS7_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS7_ID/tasks/" '{"name":"Design","description":"Design folding mechanism and template for batch production","units":"hours","rate":"100.00","est_qty":"3","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS7_ID/tasks/" '{"name":"Cut parts","description":"Cut all pieces for 10 easels","units":"hours","rate":"85.00","est_qty":"4","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS7_ID/tasks/" '{"name":"Shape and sand","description":"Round edges, sand all pieces to 220 grit","units":"hours","rate":"75.00","est_qty":"5","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS7_ID/tasks/" '{"name":"Hardware & assembly","description":"Install hinges and chain stops, assemble 10 units","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS7_ID/tasks/" '{"name":"Finish","description":"Apply satin finish, 2 coats","units":"hours","rate":"70.00","est_qty":"5","line_item_type":'"$LIT_PRD"'}' > /dev/null
info "Worksheet with 5 tasks"

EST7_GEN_RESP=$(post "/api/est-worksheets/$WS7_ID/generate-estimate/")
EST7_ID=$(echo "$EST7_GEN_RESP" | jval "estimate_id")
EST7_NUM=$(echo "$EST7_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST7_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST7_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST7_NUM accepted — job auto-approved"

WO7_RESP=$(post "/api/work-orders/" '{"job": '"$JOB7_ID"'}')
WO7_ID=$(echo "$WO7_RESP" | jval "work_order_id")
post "/api/work-orders/$WO7_ID/tasks/" '{"name":"Design","description":"Design folding mechanism and template for batch production","units":"hours","rate":"100.00","est_qty":"3","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/" '{"name":"Cut parts","description":"Cut all pieces for 10 easels","units":"hours","rate":"85.00","est_qty":"4","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/" '{"name":"Shape and sand","description":"Round edges, sand all pieces to 220 grit","units":"hours","rate":"75.00","est_qty":"5","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/" '{"name":"Hardware & assembly","description":"Install hinges and chain stops, assemble 10 units","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/" '{"name":"Finish","description":"Apply satin finish, 2 coats","units":"hours","rate":"70.00","est_qty":"5","line_item_type":'"$LIT_PRD"'}' > /dev/null
info "Work order with 5 tasks"

# Start and complete first 2 tasks, start 3rd (in progress)
WO7_TIDS=($(get_wo_task_ids "$WO7_ID"))
post "/api/work-orders/$WO7_ID/tasks/${WO7_TIDS[0]}/start/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/${WO7_TIDS[0]}/complete/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/${WO7_TIDS[1]}/start/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/${WO7_TIDS[1]}/complete/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/${WO7_TIDS[2]}/start/" '{}' > /dev/null
info "2 tasks complete, 1 in progress, 2 pending"

post "/api/jobs/$JOB7_ID/notes/" '{"text":"Design complete. All parts cut. Currently shaping and sanding — about halfway through the batch."}' > /dev/null

# ═══════════════════════════════════════════════
# SCENARIO 5: Pacific Crest Hospitality — approved jobs
# ═══════════════════════════════════════════════

log "Creating contact at Pacific Crest Hospitality..."

CONTACT8_RESP=$(post "/api/contacts/" '{
    "first_name": "Elena",
    "last_name": "Vasquez",
    "email": "evasquez@pacificcrest.example.com",
    "work_number": "206-555-0540",
    "mobile_number": "206-555-0549",
    "addr1": "900 Pike St",
    "addr2": "Floor 14",
    "city": "Seattle",
    "municipality": "WA",
    "postal_code": "98101",
    "country_code": "US"
}')
CONTACT8_ID=$(echo "$CONTACT8_RESP" | jval "contact_id")
info "Contact: Elena Vasquez (id=$CONTACT8_ID)"

BIZ4_RESP=$(post "/api/businesses/" '{
    "business_name": "Pacific Crest Hospitality Group",
    "business_address": "900 Pike St, Floor 14, Seattle WA 98101",
    "business_phone": "206-555-0500",
    "website": "https://pacificcrest.example.com",
    "default_contact_id": '"$CONTACT8_ID"'
}')
BIZ4_ID=$(echo "$BIZ4_RESP" | jval "business_id")
info "Business: Pacific Crest Hospitality Group (id=$BIZ4_ID)"

post "/api/businesses/$BIZ4_ID/notes/" '{"text":"Hotel management group. Elena handles all FF&E procurement for renovations. Net 30 terms, always pays on time. Big potential for repeat work."}' > /dev/null

# --- Job 8: APPROVED — est accepted, WO created, no invoice yet ---
log "Creating approved job with WO, no invoice (Elena)..."
JOB8_RESP=$(post "/api/jobs/" '{
    "name": "Hotel lobby accent wall panels",
    "contact": '"$CONTACT8_ID"',
    "customer_po_number": "PCH-2026-114",
    "description": "6 accent wall panels for lobby renovation at The Pinnacle Hotel. Slatted white oak over painted MDF backing, each panel 4ft x 8ft. Integrated LED uplighting."
}')
JOB8_ID=$(echo "$JOB8_RESP" | jval "job_id")
JOB8_NUM=$(echo "$JOB8_RESP" | jval "job_number")
info "Job: $JOB8_NUM (id=$JOB8_ID)"

post "/api/jobs/$JOB8_ID/notes/" '{"text":"Elena sent architectural drawings from their designer. Panels need to match existing millwork in the elevator lobby. White oak sourced from same mill as original build."}' > /dev/null

WS8_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB8_ID"'}')
WS8_ID=$(echo "$WS8_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"Site visit & measure","description":"Measure walls at The Pinnacle Hotel lobby","units":"hours","rate":"200.00","est_qty":"2","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"CAD & shop drawings","description":"Detailed drawings for 6 panels with LED routing","units":"hours","rate":"150.00","est_qty":"10","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"Mill white oak slats","description":"Mill slats to 3/4 x 1-1/2 in strips, 8ft long","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"Build MDF backing panels","description":"Cut and paint 6 MDF backing panels","units":"hours","rate":"75.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"Assemble panels","description":"Attach slats to backing with spacing jig","units":"hours","rate":"85.00","est_qty":"12","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"LED integration","description":"Route channels, install LED strips and drivers","units":"hours","rate":"75.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"Finish","description":"Sand and apply 3 coats satin clear","units":"hours","rate":"70.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS8_ID/tasks/" '{"name":"Install on-site","description":"Transport and install at hotel, 2 person crew","units":"hours","rate":"100.00","est_qty":"8","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Worksheet with 8 tasks"

EST8_GEN_RESP=$(post "/api/est-worksheets/$WS8_ID/generate-estimate/")
EST8_ID=$(echo "$EST8_GEN_RESP" | jval "estimate_id")
EST8_NUM=$(echo "$EST8_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST8_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST8_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST8_NUM accepted — job auto-approved"

WO8_RESP=$(post "/api/work-orders/" '{"job": '"$JOB8_ID"'}')
WO8_ID=$(echo "$WO8_RESP" | jval "work_order_id")
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"Site visit & measure","description":"Measure walls at The Pinnacle Hotel lobby","units":"hours","rate":"200.00","est_qty":"2","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"CAD & shop drawings","description":"Detailed drawings for 6 panels with LED routing","units":"hours","rate":"150.00","est_qty":"10","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"Mill white oak slats","description":"Mill slats to 3/4 x 1-1/2 in strips, 8ft long","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"Build MDF backing panels","description":"Cut and paint 6 MDF backing panels","units":"hours","rate":"75.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"Assemble panels","description":"Attach slats to backing with spacing jig","units":"hours","rate":"85.00","est_qty":"12","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"LED integration","description":"Route channels, install LED strips and drivers","units":"hours","rate":"75.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"Finish","description":"Sand and apply 3 coats satin clear","units":"hours","rate":"70.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO8_ID/tasks/" '{"name":"Install on-site","description":"Transport and install at hotel, 2 person crew","units":"hours","rate":"100.00","est_qty":"8","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Work order with 8 tasks — approved, no invoice, not started yet"

# --- Job 9: APPROVED — est accepted, WO created, deposit invoice sent ---
log "Creating approved job with deposit invoice sent (Elena)..."
JOB9_RESP=$(post "/api/jobs/" '{
    "name": "Custom headboards for hotel renovation (12 units)",
    "contact": '"$CONTACT8_ID"',
    "customer_po_number": "PCH-2026-118",
    "description": "12 upholstered headboards with white oak frame, king size. Integrated reading lights and USB charging. For rooms 801-812 at The Pinnacle Hotel."
}')
JOB9_ID=$(echo "$JOB9_RESP" | jval "job_id")
JOB9_NUM=$(echo "$JOB9_RESP" | jval "job_number")
info "Job: $JOB9_NUM (id=$JOB9_ID)"

post "/api/jobs/$JOB9_ID/notes/" '{"text":"Elena wants these to match the lobby panels project. Same white oak, same finish. Upholstery subcontracted to her preferred vendor after we build the frames."}' > /dev/null

WS9_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB9_ID"'}')
WS9_ID=$(echo "$WS9_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"CAD & detailing","description":"Shop drawings for headboard frame with electrical routing","units":"hours","rate":"150.00","est_qty":"6","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"Jig fabrication","description":"Build assembly jig for batch of 12","units":"hours","rate":"150.00","est_qty":"4","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"Mill & cut","description":"Mill white oak frame pieces for 12 headboards","units":"hours","rate":"85.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"Route electrical","description":"Route channels for reading lights and USB, 12 units","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"Assemble frames","description":"Assemble 12 headboard frames with jig","units":"hours","rate":"85.00","est_qty":"16","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"Finish","description":"Sand and finish 12 frames, satin clear","units":"hours","rate":"70.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS9_ID/tasks/" '{"name":"Deliver to upholsterer","description":"Deliver finished frames to upholstery vendor","units":"-","rate":"150.00","est_qty":"1","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Worksheet with 7 tasks"

EST9_GEN_RESP=$(post "/api/est-worksheets/$WS9_ID/generate-estimate/")
EST9_ID=$(echo "$EST9_GEN_RESP" | jval "estimate_id")
EST9_NUM=$(echo "$EST9_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST9_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST9_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST9_NUM accepted — job auto-approved"

WO9_RESP=$(post "/api/work-orders/" '{"job": '"$JOB9_ID"'}')
WO9_ID=$(echo "$WO9_RESP" | jval "work_order_id")
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"CAD & detailing","description":"Shop drawings for headboard frame with electrical routing","units":"hours","rate":"150.00","est_qty":"6","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"Jig fabrication","description":"Build assembly jig for batch of 12","units":"hours","rate":"150.00","est_qty":"4","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"Mill & cut","description":"Mill white oak frame pieces for 12 headboards","units":"hours","rate":"85.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"Route electrical","description":"Route channels for reading lights and USB, 12 units","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"Assemble frames","description":"Assemble 12 headboard frames with jig","units":"hours","rate":"85.00","est_qty":"16","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"Finish","description":"Sand and finish 12 frames, satin clear","units":"hours","rate":"70.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO9_ID/tasks/" '{"name":"Deliver to upholsterer","description":"Deliver finished frames to upholstery vendor","units":"-","rate":"150.00","est_qty":"1","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Work order with 7 tasks"

# Deposit invoice — 50% upfront
INV9_RESP=$(post "/api/invoices/" '{"job": '"$JOB9_ID"'}')
INV9_ID=$(echo "$INV9_RESP" | jval "invoice_id")
INV9_NUM=$(echo "$INV9_RESP" | jval "invoice_number")
post "/api/invoices/$INV9_ID/line-items/" '{"description":"Deposit — 50% of estimated project total","qty":"1","units":"lot","price":"4500.00"}' > /dev/null
patch "/api/invoices/$INV9_ID/" '{"status":"open"}' > /dev/null
info "Deposit invoice $INV9_NUM sent (open)"

post "/api/jobs/$JOB9_ID/notes/" '{"text":"Deposit invoice sent to Elena. She said AP will process within 2 weeks. Not starting fabrication until deposit clears."}' > /dev/null

# ═══════════════════════════════════════════════
# SCENARIO 6: Solo contact — rejected job
# ═══════════════════════════════════════════════

log "Creating solo contact (James Whitfield)..."
CONTACT9_RESP=$(post "/api/contacts/" '{
    "first_name": "James",
    "last_name": "Whitfield",
    "email": "jwhitfield@example.com",
    "mobile_number": "971-555-0612",
    "addr1": "3422 SE Hawthorne Blvd",
    "city": "Portland",
    "municipality": "OR",
    "postal_code": "97214",
    "country_code": "US"
}')
CONTACT9_ID=$(echo "$CONTACT9_RESP" | jval "contact_id")
info "Contact: James Whitfield (id=$CONTACT9_ID) — no business"

# --- Job 10: REJECTED ---
log "Creating rejected job (James)..."
JOB10_RESP=$(post "/api/jobs/" '{
    "name": "Backyard pergola with built-in planters",
    "contact": '"$CONTACT9_ID"',
    "description": "Cedar pergola, 12ft x 10ft, with integrated planter boxes at each post. Needs to support wisteria vine. Residential backyard installation."
}')
JOB10_ID=$(echo "$JOB10_RESP" | jval "job_id")
JOB10_NUM=$(echo "$JOB10_RESP" | jval "job_number")
info "Job: $JOB10_NUM (id=$JOB10_ID)"

post "/api/jobs/$JOB10_ID/notes/" '{"text":"James found us through Yelp. Wants a pergola but seems surprised by custom pricing. Mentioned a Home Depot kit as an alternative."}' > /dev/null

WS10_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB10_ID"'}')
WS10_ID=$(echo "$WS10_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS10_ID/tasks/" '{"name":"Site visit","description":"Measure backyard, check for utilities, assess ground conditions","units":"hours","rate":"200.00","est_qty":"1.5","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS10_ID/tasks/" '{"name":"Design","description":"Pergola and planter design with structural calcs","units":"hours","rate":"150.00","est_qty":"4","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS10_ID/tasks/" '{"name":"Cut cedar","description":"Mill and cut all cedar members","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS10_ID/tasks/" '{"name":"Build planters","description":"Fabricate 4 planter boxes with drainage","units":"hours","rate":"85.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS10_ID/tasks/" '{"name":"Install","description":"On-site assembly, set posts in concrete, 2 crew","units":"hours","rate":"100.00","est_qty":"12","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Worksheet with 5 tasks"

EST10_GEN_RESP=$(post "/api/est-worksheets/$WS10_ID/generate-estimate/")
EST10_ID=$(echo "$EST10_GEN_RESP" | jval "estimate_id")
EST10_NUM=$(echo "$EST10_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST10_ID/mark-open/" '{}' > /dev/null
info "Estimate $EST10_NUM sent"

# Client rejects the estimate, then we reject the job
patch "/api/estimates/$EST10_ID/" '{"status":"rejected"}' > /dev/null
patch "/api/jobs/$JOB10_ID/" '{"status":"rejected"}' > /dev/null
info "Estimate rejected, job $JOB10_NUM rejected"

post "/api/jobs/$JOB10_ID/notes/" '{"text":"James called back — says the estimate is way above his budget. Going to buy a kit from a big box store instead. Politely declined to negotiate."}' > /dev/null

# ═══════════════════════════════════════════════
# SCENARIO 7: Solo contact — two jobs, in-progress and completed
# ═══════════════════════════════════════════════

log "Creating solo contact (Aisha Okafor)..."
CONTACT10_RESP=$(post "/api/contacts/" '{
    "first_name": "Aisha",
    "last_name": "Okafor",
    "email": "aisha@spiceroutepdx.example.com",
    "mobile_number": "503-555-0715",
    "addr1": "2815 NE Alberta St",
    "city": "Portland",
    "municipality": "OR",
    "postal_code": "97211",
    "country_code": "US"
}')
CONTACT10_ID=$(echo "$CONTACT10_RESP" | jval "contact_id")
info "Contact: Aisha Okafor (id=$CONTACT10_ID) — no business"

post "/api/contacts/$CONTACT10_ID/notes/" '{"text":"Owns Spice Route restaurant on Alberta. Hands-on owner, very particular about design. Prefers texting over email."}' > /dev/null

# --- Job 11: APPROVED — deposit paid, WO complete, ready for final invoice ---
log "Creating in-progress job, deposit paid, WO complete (Aisha)..."
JOB11_RESP=$(post "/api/jobs/" '{
    "name": "Restaurant service counter with display case",
    "contact": '"$CONTACT10_ID"',
    "description": "L-shaped service counter, 10ft x 6ft, walnut top with steel frame. Integrated pastry display case with glass panels. Power and data at 3 POS stations."
}')
JOB11_ID=$(echo "$JOB11_RESP" | jval "job_id")
JOB11_NUM=$(echo "$JOB11_RESP" | jval "job_number")
info "Job: $JOB11_NUM (id=$JOB11_ID)"

post "/api/jobs/$JOB11_ID/notes/" '{"text":"Aisha closing the restaurant for 2 weeks for renovation. Counter needs to be ready for install on day 3 of the closure. Very tight timeline."}' > /dev/null

WS11_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB11_ID"'}')
WS11_ID=$(echo "$WS11_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Site measure","description":"Measure restaurant, coordinate with electrician","units":"hours","rate":"200.00","est_qty":"2","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Design","description":"CAD drawings, steel frame shop drawings","units":"hours","rate":"150.00","est_qty":"8","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Steel frame fabrication","description":"Weld steel base frame, powder coat","units":"hours","rate":"100.00","est_qty":"12","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Walnut top","description":"Glue up, flatten, and shape walnut counter top","units":"hours","rate":"85.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Display case","description":"Build display case frame, install glass panels","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Finish","description":"Sand and oil walnut, final assembly","units":"hours","rate":"70.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS11_ID/tasks/" '{"name":"Install","description":"Deliver, set counter, connect power, 2 person crew","units":"hours","rate":"100.00","est_qty":"6","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Worksheet with 7 tasks"

EST11_GEN_RESP=$(post "/api/est-worksheets/$WS11_ID/generate-estimate/")
EST11_ID=$(echo "$EST11_GEN_RESP" | jval "estimate_id")
EST11_NUM=$(echo "$EST11_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST11_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST11_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST11_NUM accepted — job auto-approved"

WO11_RESP=$(post "/api/work-orders/" '{"job": '"$JOB11_ID"'}')
WO11_ID=$(echo "$WO11_RESP" | jval "work_order_id")
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Site measure","description":"Measure restaurant, coordinate with electrician","units":"hours","rate":"200.00","est_qty":"2","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Design","description":"CAD drawings, steel frame shop drawings","units":"hours","rate":"150.00","est_qty":"8","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Steel frame fabrication","description":"Weld steel base frame, powder coat","units":"hours","rate":"100.00","est_qty":"12","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Walnut top","description":"Glue up, flatten, and shape walnut counter top","units":"hours","rate":"85.00","est_qty":"10","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Display case","description":"Build display case frame, install glass panels","units":"hours","rate":"85.00","est_qty":"8","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Finish","description":"Sand and oil walnut, final assembly","units":"hours","rate":"70.00","est_qty":"6","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO11_ID/tasks/" '{"name":"Install","description":"Deliver, set counter, connect power, 2 person crew","units":"hours","rate":"100.00","est_qty":"6","line_item_type":'"$LIT_DLV"'}' > /dev/null
complete_all_tasks "$WO11_ID"
info "All tasks started+completed (WO auto-completed)"

# Deposit invoice — paid
INV11_RESP=$(post "/api/invoices/" '{"job": '"$JOB11_ID"'}')
INV11_ID=$(echo "$INV11_RESP" | jval "invoice_id")
INV11_NUM=$(echo "$INV11_RESP" | jval "invoice_number")
post "/api/invoices/$INV11_ID/line-items/" '{"description":"Deposit — 50% of project total","qty":"1","units":"lot","price":"3800.00"}' > /dev/null
patch "/api/invoices/$INV11_ID/" '{"status":"open"}' > /dev/null
patch "/api/invoices/$INV11_ID/" '{"status":"paid"}' > /dev/null
info "Deposit invoice $INV11_NUM paid — ready for final invoice"

post "/api/jobs/$JOB11_ID/notes/" '{"text":"All fabrication complete. Counter installed during closure week, Aisha is thrilled. Need to generate final invoice for remaining balance."}' > /dev/null

# --- Job 12: COMPLETED — all done, final invoice sent ---
log "Creating completed job with final invoice sent (Aisha)..."
JOB12_RESP=$(post "/api/jobs/" '{
    "name": "Spice display shelving unit",
    "contact": '"$CONTACT10_ID"',
    "description": "Wall-mounted spice display, 6ft wide x 4ft tall. Walnut shelves with steel brackets, matching the service counter. Backlit with warm LED strip."
}')
JOB12_ID=$(echo "$JOB12_RESP" | jval "job_id")
JOB12_NUM=$(echo "$JOB12_RESP" | jval "job_number")
info "Job: $JOB12_NUM (id=$JOB12_ID)"

post "/api/jobs/$JOB12_ID/notes/" '{"text":"Follow-up project from the counter job. Aisha wants the same walnut and steel look for a spice display behind the register. Small job, quick turnaround."}' > /dev/null

WS12_RESP=$(post "/api/est-worksheets/" '{"job": '"$JOB12_ID"'}')
WS12_ID=$(echo "$WS12_RESP" | jval "est_worksheet_id")
post "/api/est-worksheets/$WS12_ID/tasks/" '{"name":"Design","description":"Layout and bracket design","units":"hours","rate":"100.00","est_qty":"2","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/est-worksheets/$WS12_ID/tasks/" '{"name":"Cut & shape walnut","description":"Mill shelves from walnut offcuts","units":"hours","rate":"85.00","est_qty":"3","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS12_ID/tasks/" '{"name":"Weld brackets","description":"Fabricate 8 steel shelf brackets","units":"hours","rate":"100.00","est_qty":"2","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS12_ID/tasks/" '{"name":"Finish & LED","description":"Oil shelves, install LED strip on top shelf","units":"hours","rate":"70.00","est_qty":"3","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/est-worksheets/$WS12_ID/tasks/" '{"name":"Install","description":"Mount brackets and shelves on-site","units":"hours","rate":"100.00","est_qty":"2","line_item_type":'"$LIT_DLV"'}' > /dev/null
info "Worksheet with 5 tasks"

EST12_GEN_RESP=$(post "/api/est-worksheets/$WS12_ID/generate-estimate/")
EST12_ID=$(echo "$EST12_GEN_RESP" | jval "estimate_id")
EST12_NUM=$(echo "$EST12_GEN_RESP" | jval "estimate_number")
post "/api/estimates/$EST12_ID/mark-open/" '{}' > /dev/null
patch "/api/estimates/$EST12_ID/" '{"status":"accepted"}' > /dev/null
info "Estimate $EST12_NUM accepted — job auto-approved"

WO12_RESP=$(post "/api/work-orders/" '{"job": '"$JOB12_ID"'}')
WO12_ID=$(echo "$WO12_RESP" | jval "work_order_id")
post "/api/work-orders/$WO12_ID/tasks/" '{"name":"Design","description":"Layout and bracket design","units":"hours","rate":"100.00","est_qty":"2","line_item_type":'"$LIT_SVC"'}' > /dev/null
post "/api/work-orders/$WO12_ID/tasks/" '{"name":"Cut & shape walnut","description":"Mill shelves from walnut offcuts","units":"hours","rate":"85.00","est_qty":"3","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO12_ID/tasks/" '{"name":"Weld brackets","description":"Fabricate 8 steel shelf brackets","units":"hours","rate":"100.00","est_qty":"2","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO12_ID/tasks/" '{"name":"Finish & LED","description":"Oil shelves, install LED strip on top shelf","units":"hours","rate":"70.00","est_qty":"3","line_item_type":'"$LIT_PRD"'}' > /dev/null
post "/api/work-orders/$WO12_ID/tasks/" '{"name":"Install","description":"Mount brackets and shelves on-site","units":"hours","rate":"100.00","est_qty":"2","line_item_type":'"$LIT_DLV"'}' > /dev/null
complete_all_tasks "$WO12_ID"
info "All tasks started+completed (WO auto-completed)"

# Final invoice
INV12_RESP=$(post "/api/invoices/" '{"job": '"$JOB12_ID"'}')
INV12_ID=$(echo "$INV12_RESP" | jval "invoice_id")
INV12_NUM=$(echo "$INV12_RESP" | jval "invoice_number")
post "/api/invoices/$INV12_ID/line-items/" '{"description":"Design — layout and bracket design","qty":"2","units":"hours","price":"100.00"}' > /dev/null
post "/api/invoices/$INV12_ID/line-items/" '{"description":"Walnut shelves — milling and shaping","qty":"3","units":"hours","price":"85.00"}' > /dev/null
post "/api/invoices/$INV12_ID/line-items/" '{"description":"Steel brackets — fabrication (8 pcs)","qty":"2","units":"hours","price":"100.00"}' > /dev/null
post "/api/invoices/$INV12_ID/line-items/" '{"description":"Finishing and LED installation","qty":"3","units":"hours","price":"70.00"}' > /dev/null
post "/api/invoices/$INV12_ID/line-items/" '{"description":"On-site installation","qty":"2","units":"hours","price":"100.00"}' > /dev/null
patch "/api/invoices/$INV12_ID/" '{"status":"open"}' > /dev/null
info "Final invoice $INV12_NUM sent (open)"

post "/api/jobs/$JOB12_ID/complete/" '{}' > /dev/null
post "/api/jobs/$JOB12_ID/notes/" '{"text":"Installed and looks great. Aisha posted photos on Instagram. Final invoice sent, awaiting payment."}' > /dev/null
info "Job $JOB12_NUM completed"

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
echo "  === Scenario 4: Cascade Event Rentals ==="
echo "  Business:  Cascade Event Rentals (id=$BIZ3_ID)"
echo "  Contacts:  Priya Sharma (id=$CONTACT6_ID), Ben Nakamura (id=$CONTACT7_ID)"
echo "  Job:       $JOB5_NUM (id=$JOB5_ID) — DRAFT (worksheet + estimate, nothing sent)"
echo "  Job:       $JOB6_NUM (id=$JOB6_ID) — SUBMITTED (estimate sent, worksheet frozen)"
echo "  Job:       $JOB7_NUM (id=$JOB7_ID) — APPROVED (2 tasks complete, 1 in progress, 2 pending)"
echo ""
echo "  === Scenario 5: Pacific Crest Hospitality ==="
echo "  Business:  Pacific Crest Hospitality Group (id=$BIZ4_ID)"
echo "  Contact:   Elena Vasquez (id=$CONTACT8_ID)"
echo "  Job:       $JOB8_NUM (id=$JOB8_ID) — APPROVED (est accepted, WO ready, no invoice)"
echo "  Job:       $JOB9_NUM (id=$JOB9_ID) — APPROVED (est accepted, WO ready, deposit sent)"
echo ""
echo "  === Scenario 6: Solo — rejected ==="
echo "  Contact:   James Whitfield (id=$CONTACT9_ID) — no business"
echo "  Job:       $JOB10_NUM (id=$JOB10_ID) — REJECTED"
echo ""
echo "  === Scenario 7: Solo — in-progress + completed ==="
echo "  Contact:   Aisha Okafor (id=$CONTACT10_ID) — no business"
echo "  Job:       $JOB11_NUM (id=$JOB11_ID) — APPROVED (WO complete, deposit paid, needs final invoice)"
echo "  Job:       $JOB12_NUM (id=$JOB12_ID) — COMPLETED (final invoice sent)"
echo ""

rm -f "$COOKIE_JAR"

# ─────────────────────────────────────────────
# Create test users with different permission groups
# ─────────────────────────────────────────────
log "Creating test users..."
python manage.py shell -c "
from apps.core.models import User
from django.contrib.auth.models import Group

users = [
    ('worker1', 'W', 'Worker'),
    ('bookkeeper1', 'B', 'Bookkeeper'),
    ('manager1', 'M', 'Manager'),
]
for username, password, group_name in users:
    u, created = User.objects.get_or_create(username=username)
    u.set_password(password)
    u.save()
    u.groups.set([Group.objects.get(name=group_name)])
    print(f\"  {'Created' if created else 'Updated'} {username} ({group_name})\")
"
info "Test users ready (passwords: W, B, M)"

# update timestamps in the db
mysql -u root minibini_db < scripts/spread_timestamps.sql
