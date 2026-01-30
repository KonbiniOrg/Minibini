from .populate_data import Command as BaseCommand


class Command(BaseCommand):
    """Command to populate job-specific test data."""

    fixture_dir = 'job_data'
    help = 'Drop and recreate database with job test data for development'

# when a significant db change has occured and the fixture data needs to be updated,
# use the dumpdata into a temp file (unless you're super confident nothing extra exists)
# and merge by hand.
#
# 01_base.json is created with this command:
# python manage.py dumpdata auth.group core.user core.configuration contacts.contact contacts.business contacts.paymentterms jobs.taskmapping jobs.tasktemplate jobs.workordertemplate invoicing.pricelistitem jobs.templatetaskassociation jobs.productbundlingrule --indent 2 > TEMPFILE
#
# 02_simple_jobs.json is created with this:
# py manage.py dumpdata jobs.job jobs.estimate jobs.estworksheet jobs.task jobs.blep jobs.estimatelineitem jobs.workorder invoicing.invoice invoicing.invoicelineitem jobs.taskinstancemapping --indent 2
#
# 03_simple_purch.json is created with this:
# py manage.py dumpdata purchasing.bill purchasing.billlineitem purchasing.purchaseorder purchasing.purchaseorderlineitem --indent 2
#