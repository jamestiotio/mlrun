# Copyright 2024 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json
import time
import typing

import pytest
import requests

import mlrun
import mlrun.common.schemas.alert as alert_constants
import mlrun.common.schemas.model_monitoring.constants as mm_constants
import mlrun.model_monitoring.api
from mlrun.datastore import get_stream_pusher
from mlrun.model_monitoring.helpers import get_stream_path
from tests.system.base import TestMLRunSystem


@TestMLRunSystem.skip_test_if_env_not_configured
class TestAlerts(TestMLRunSystem):
    project_name = "alerts-test-project"

    # Set image to "<repo>/mlrun:<tag>" for local testing
    image: typing.Optional[str] = None

    def test_job_failure_alert(self):
        """
        validate that an alert is sent in case a job fails
        """
        self.project.set_function(
            name="test-func",
            func="assets/function.py",
            handler="handler",
            image="mlrun/mlrun" if self.image is None else self.image,
            kind="job",
        )

        # nuclio function for storing notifications, to validate that alert notifications were sent on the failed job
        nuclio_function_url = self._deploy_notification_nuclio()

        # create an alert with webhook notification
        alert_name = "failure_webhook"
        alert_summary = "Job failed"
        notifications = self._generate_failure_notifications(nuclio_function_url)
        self._create_alert_config(
            self.project_name,
            alert_name,
            alert_constants.EventEntityKind.JOB,
            alert_summary,
            alert_constants.EventKind.FAILED,
            notifications,
        )

        with pytest.raises(Exception):
            self.project.run_function("test-func")

        # in order to trigger the periodic monitor runs function, to detect the failed run and send an event on it
        time.sleep(35)

        # Validate that the notifications was sent on the failed job
        expected_notifications = ["notification failure"]
        self._validate_notifications_on_nuclio(
            nuclio_function_url, expected_notifications
        )

    def test_drift_detection_alert(self):
        """
        validate that an alert is sent in case of a model drift detection
        """

        # deploy nuclio func for storing notifications, to validate an alert notifications were sent on drift detection
        nuclio_function_url = self._deploy_notification_nuclio()

        # create an alert with two webhook notifications
        alert_name = "drift_webhook"
        alert_summary = "Model is drifting"
        notifications = self._generate_drift_notifications(nuclio_function_url)
        self._create_alert_config(
            self.project_name,
            alert_name,
            alert_constants.EventEntityKind.MODEL,
            alert_summary,
            alert_constants.EventKind.DRIFT_DETECTED,
            notifications,
        )

        self.project.enable_model_monitoring(image=self.image or "mlrun/mlrun")

        writer = self.project.get_function(
            key=mm_constants.MonitoringFunctionNames.WRITER
        )
        writer._wait_for_function_deployment(db=writer._get_db())
        endpoint_id = "demo-endpoint"
        mlrun.model_monitoring.api.get_or_create_model_endpoint(
            project=self.project.metadata.name,
            endpoint_id=endpoint_id,
            context=mlrun.get_or_create_ctx("demo"),
        )
        stream_uri = get_stream_path(
            project=self.project.metadata.name,
            function_name=mm_constants.MonitoringFunctionNames.WRITER,
        )
        output_stream = get_stream_pusher(
            stream_uri,
        )

        data = {
            mm_constants.WriterEvent.ENDPOINT_ID: endpoint_id,
            mm_constants.WriterEvent.APPLICATION_NAME: mm_constants.HistogramDataDriftApplicationConstants.NAME,
            mm_constants.WriterEvent.RESULT_NAME: "data_drift_test",
            mm_constants.WriterEvent.RESULT_VALUE: 0.5,
            mm_constants.WriterEvent.RESULT_STATUS: mm_constants.ResultStatusApp.detected,
            mm_constants.WriterEvent.RESULT_KIND: mm_constants.ResultKindApp.data_drift,
            mm_constants.WriterEvent.RESULT_EXTRA_DATA: {"threshold": 0.3},
            mm_constants.WriterEvent.START_INFER_TIME: "2023-09-11T12:00:00",
            mm_constants.WriterEvent.END_INFER_TIME: "2023-09-11T12:01:00",
            mm_constants.WriterEvent.CURRENT_STATS: json.dumps("a"),
        }
        output_stream.push([data])

        # wait for the nuclio function to check for the stream inputs
        time.sleep(10)

        # Validate that the notifications were sent on the drift
        expected_notifications = ["first drift", "second drift"]
        self._validate_notifications_on_nuclio(
            nuclio_function_url, expected_notifications
        )

    def _deploy_notification_nuclio(self):
        nuclio_function = self.project.set_function(
            name="nuclio",
            func="assets/notification_nuclio_function.py",
            image="mlrun/mlrun" if self.image is None else self.image,
            kind="nuclio",
        )
        nuclio_function.deploy()
        return nuclio_function.spec.command

    @staticmethod
    def _generate_failure_notifications(nuclio_function_url):
        return [
            {
                "kind": "webhook",
                "name": "failure",
                "message": "job failed !",
                "severity": "warning",
                "when": ["now"],
                "condition": "failed",
                "params": {
                    "url": nuclio_function_url,
                    "override_body": {
                        "operation": "add",
                        "data": "notification failure",
                    },
                },
                "secret_params": {
                    "webhook": "some-webhook",
                },
            },
        ]

    @staticmethod
    def _generate_drift_notifications(nuclio_function_url):
        return [
            {
                "kind": "webhook",
                "name": "drift",
                "message": "A drift was detected",
                "severity": "warning",
                "when": ["now"],
                "condition": "failed",
                "params": {
                    "url": nuclio_function_url,
                    "override_body": {
                        "operation": "add",
                        "data": "first drift",
                    },
                },
                "secret_params": {
                    "webhook": "some-webhook",
                },
            },
            {
                "kind": "webhook",
                "name": "drift2",
                "message": "A drift was detected",
                "severity": "warning",
                "when": ["now"],
                "condition": "failed",
                "params": {
                    "url": nuclio_function_url,
                    "override_body": {
                        "operation": "add",
                        "data": "second drift",
                    },
                },
                "secret_params": {
                    "webhook": "some-webhook",
                },
            },
        ]

    @staticmethod
    def _create_alert_config(
        project,
        name,
        entity_kind,
        summary,
        event_name,
        notifications,
        criteria=None,
    ):
        alert_data = mlrun.common.schemas.AlertConfig(
            project=project,
            name=name,
            summary=summary,
            severity="low",
            entity={"kind": entity_kind, "project": project, "id": "*"},
            trigger={"events": [event_name]},
            criteria=criteria,
            notifications=notifications,
        )

        mlrun.get_run_db().store_alert_config(name, alert_data)

    @staticmethod
    def _validate_notifications_on_nuclio(nuclio_function_url, expected_notifications):
        response = requests.post(nuclio_function_url, json={"operation": "list"})
        response_data = json.loads(response.text)

        # Extract notification data from the response
        notifications = response_data["data_list"]

        for expected_notification in expected_notifications:
            assert expected_notification in notifications

        requests.post(nuclio_function_url, json={"operation": "reset"})
