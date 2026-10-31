"""Admit a full manual refresh in the runner, then execute the regular worker."""

from ..repository.admission import admit_run
from ..repository.connection import connection_failure_diagnostic
from .admission import AdmissionError
from .worker import run_worker


def run_manual(run_id=None, **parameters):
    logger = parameters["logger"]
    if run_id is None:
        try:
            with parameters["connection_factory"]() as connection:
                admitted = admit_run(connection, parameters["settings"].enabled_chains)
            run_id = admitted.id
        except Exception as error:
            code, message = connection_failure_diagnostic(error)
            if isinstance(error, AdmissionError):
                code, message = str(error), "Manual refresh admission failed"
            logger.error("run.admission_failed", message, error_code=code, error=error)
            return 1
        logger.info("run.admitted", "Manual refresh admitted automatically", run_id=str(run_id))
    return run_worker(run_id, **parameters)
