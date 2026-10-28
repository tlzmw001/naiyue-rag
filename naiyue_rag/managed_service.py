"""Start on absence, verify readiness, and stop only the exact owned child."""
import logging
import subprocess
import sys
import tempfile
import time
import uuid
from .local_client import LocalClient,LocalServiceError

LOGGER=logging.getLogger(__name__)


def _close(resource):
    try:resource.close();return True
    except Exception:
        LOGGER.error('service_shutdown_failed code=service_resource_close_failed');return False


class ManagedConnection:
    def __init__(self,settings):
        self.settings=settings;self.client=LocalClient(settings);self.process=None;self._stderr=None

    def __enter__(self):
        try:
            try:self.client.health();return self
            except LocalServiceError as error:
                if error.code!='service_unavailable':raise
            instance=uuid.uuid4().hex
            self._stderr=tempfile.TemporaryFile()
            self.process=subprocess.Popen([sys.executable,'-m','naiyue_rag','--config',self.settings.config_path,
                '--parent-watch','--instance-id',instance],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self._stderr)
            deadline=time.monotonic()+self.settings.service.startup_timeout_seconds
            while True:
                if self.process.poll() is not None:raise LocalServiceError('service_start_failed')
                remaining=deadline-time.monotonic()
                if remaining<=0:raise LocalServiceError('service_start_timeout')
                try:
                    health=self.client.health(timeout=remaining)
                    if health['instance_id']!=instance:raise LocalServiceError('service_identity_mismatch')
                    return self
                except LocalServiceError as error:
                    if error.code!='service_unavailable':raise
                remaining=deadline-time.monotonic()
                if remaining<=0:raise LocalServiceError('service_start_timeout')
                time.sleep(min(.05,remaining))
        except BaseException:
            self.__exit__(*sys.exc_info());raise

    def __exit__(self,exc_type,exc_value,traceback):
        failed=False
        try:
            if self.process is not None:
                if self.process.stdin is not None:failed=not _close(self.process.stdin) or failed
                try:self.process.wait(timeout=self.settings.service.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    LOGGER.error('service_shutdown_failed code=service_shutdown_timeout')
                    self.process.terminate()
                    try:self.process.wait(timeout=self.settings.service.shutdown_timeout_seconds)
                    except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
                    failed=True
        except Exception:
            failed=True;LOGGER.error('service_shutdown_failed code=service_shutdown_failed')
        finally:
            failed=not _close(self.client) or failed
            if self._stderr is not None:failed=not _close(self._stderr) or failed
        if failed and exc_type is None:raise LocalServiceError('service_shutdown_failed')
        return False
