from django.test import SimpleTestCase

from zog.station_access.api.serializers import application_json
from zog.station_access.box_control.types import ApplicationSummary


class ApplicationProvenanceSerializationTests(SimpleTestCase):
    def test_missing_application_source_identity_is_explicit(self):
        value = application_json(ApplicationSummary(
            name="browser",
            description="Browser",
            multi_instance=False,
            start_policy="externally-controlled",
        ))
        self.assertEqual(value["source_license"], {
            "state": "unavailable",
            "reason": "application-source-identity-not-published",
        })
