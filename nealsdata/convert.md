Create test data in json format from real Neal's CNC customer data by processing the downloaded spreadsheet that FreeAgent spits out.  Only consider the pages Contacts, Projects, Invoices, Estimates, Bills, Tasks, Timeslips, and Price List Items; disregard all the rest.  We will map spreadsheet data to Minibini objects like this:
    Contacts -> Contact + Business
    Projects -> Job + WorkOrder
    Invoices -> Invoice + InvoiceLineItem
    Estimate -> Estimate + EstimateLineItem
    Bills    -> Bill + BillLineItem + PurchaseOrder + PurchaseOrderLineItem
    Tasks    -> Task
    Timeslip -> Blep
    Price List Items -> PriceListItem

The spreadsheet links information together in two ways.  First, data in one page is referenced in other pages by full text of names as the spreadsheet has no GUI values.  Second, data for Estimates, Bills and Invoices combine the object data and the associated line item data into one page so those link line to next line.  Do not sort these pages or the associations are lost!

We want to delete enough old data so the size is manageable, but not break any associations.  There are 100 Projects in various states, which is plenty (and far more data without Projects).  They're all old and the task/timeslip data is minimal but we can add more of those easily enough.  So, anything old that doesn't touch a Project gets deleted.

My suggested high-level process is, pull the whole spreadsheet into memory, generate GUID numbers and set up FK references according to how the spreadsheet pages reference each other; delete stuff that doesn't EITHER touch a Project or hit one of the exception cases or have a more recent date than 2025-10-01; add Contact objects where name inconsistencies arise as noted below.

In the spreadsheet, column information maps to Object fields in ways that should be fairly obvious in general
* Contacts sheet contains both Contact and Business object data.  For each line, one Contact and 0 or 1 Businesses will be created, and the FK reference between them.  There may be a few lines that only have an Organization name and no First and Last names; in this case use the strings "(unknown)" for both names.  Some of the column headings won't apply at all and these can be discarded.
* Projects sheet should be used to generate a WorkOrder object UNLESS the status of the project is CANCELLED.  Tasks linked to a Project should be given FK references to the associated WorkOrder.  (The incoming data does not have the concept of a WorkOrder.) Generate a fake job_number for the required Job field by using the pattern J{year}-{counter:04d} based on their created date.
* Invoices, Estimates, Bills, all have line item object which on the spreadsheet are simply listed below.  So the first columns are data for the containing object, and the last columns are for the line items associated with that container.  You can tell when it switches over because the contents of the rows change.  So one line will have, e.g. Invoice data up to column Z (perhaps), and the next maybe 4 or 5 lines will have InvoiceLineItem data from columns AA onwards.  Many of the columns have data that doesn't fit our structure and can be ignored.  Generate required tracking numbers the same way as job_numbers.
* Bill data will be used to create PO data as well, such that each line will generate a PO and a Bill with the FK reference between them.  All the line item data is the same. (The incoming data does not have the concept of a PurchaseOrder.)

In the spreadsheet, page data associate as follows.  The quoted terms refer to the spreadsheet column headers in line 1, and the letter in parentheses is the column it is in.
* Contacts link to Projects by "Organization" (A) -> "Client Organization" (B) as well as "First Name" (B), "Last Name" (C) -> "Client Name" (C)
* Contacts link to Bills by "Organization" (A) -> "Contact Organization" (A) as well as "First Name" (B), "Last Name" (C) -> "Contact Name" (B)
* Projects link to Invoices by "Name" (A) -> "Projects" (C)
* Projects link to Estimates by "Name" (A) -> "Project" (A)
* Projects link to Bills by "Name" (A) -> "Project" (O)
* Projects link to Tasks by "Name" (A) -> "Project" (A)
* Projects link to Timeslips by "Name" (A) -> "Project" (G)
* Tasks link to Timeslips by "Name" (B) -> "Task" (F)

If the name and organization in the Project or Bill spreadsheet data don't match the contact data for the Business object it references (at this point we only have 1 Contact per Business), make a new Contact object with the name, associated with the Business and invent data for them similar to the data in the first Contact's.  The new Contact then becomes the FK reference for the Project or Bill.  Disregard the contact information in Estimate and Invoice spreadsheet pages.

First load the base data from fixtures/job_data/01_base.json, which contains configuration and user data and a few other starter things.  Read that into memory first so as to be able to avoid overlapping PK values.  Where Timeslips reference users, assign the existing user with the least permissions to the corresponding Blep.

Statuses don't map quite right for a couple objects.  Use these mappings:
Estimate status_map = {
      'Draft': 'draft',
      'Sent': 'open',
      'Approved': 'accepted',  # ✓ FIXED
      'Rejected': 'rejected',
  }
Job status_map = {
      'Completed': 'completed',
      'Active': 'approved',    # ✓ FIXED (maps to valid choice)
      'Cancelled': 'cancelled', # ✓ FIXED (case corrected)
  }

If there are multiple Estimates associated with a project, check if they are versioned (i.e. have a suffix of -v1 or V2 or similar). If so, mark the oldest as superseded and the latest leave its status as is.  Otherwise, create multiple Jobs from the Project, copying all data except the Estimate.

For all the line items, add line numbers starting with 1 for each main object and restarting at the next.

Complete Job Date Rules:
1. created_date: Created Date from spreadsheet
2. start_date:
  - If explicit "Starts On" exists → use it
  - Else if status='approved' → use V1 estimate date
  - Else if status='completed' AND no estimates → use created_date
  - Else → None
3. due_date: "Ends On" from spreadsheet (or None)
4. completed_date:
  - If status='approved' → None
  - Else → Updated Date from spreadsheet

TODO:
- Check Blep data when I've written the UI to view it
- Alter the handling of multiple Estimates per project when I've implemented Change Orders (project Round Desks for sure, likely others)
- dates on objects other than Jobs
- status matching - there are Jobs in completed state that have Estimates in open or rejected state, e.g. Sandisk #3 and Tree Bench - also all? of the additional Jobs from projects with multiple estimates

python nealsdata/convert_neals_data.py nealsdata/company-export-whatever.xls --output fixtures/job_data/02_nealscnc_data.json