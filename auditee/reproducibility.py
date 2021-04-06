import pathlib
from collections import namedtuple

from blessings import Terminal
from colorama import init as init_colorama  # , Fore, Back, Style
from python_on_whales import docker

from auditee.sgx import Sigstruct, sign as sgx_sign

init_colorama()
term = Terminal()

ReproducibilityReport = namedtuple(
    "ReproducibilityReport", ("mrenclave", "isvprodid", "isvsvn", "mrsigner")
)
ReportItem = namedtuple("ReportItem", ("matches", "expected", "computed"))


def verify_mrenclave(
    docker_build_attrs,
    signed_enclave,
    enclave_config,
    *,
    ias_report=None,
    unsigned_enclave_filename="Enclave.so",
):
    """Verifies if the MRENCLAVE of the provided signed enclave matches
    with the one obtained when rebuilding the enclave from source, and
    the one in the IAS report.

    Example
    -------
    docker_build_attrs = {'target': 'export-stage'}

    """
    context_path = docker_build_attrs.pop("context_path", ".")
    output = docker_build_attrs.pop("output", {"type": "local", "dest": "out"})
    # target="export-stage", output={"type": "local", "dest": "out"}
    docker.build(context_path, output=output, **docker_build_attrs)

    unsigned_enclave = pathlib.Path(output["dest"]).joinpath(unsigned_enclave_filename)
    signing_key = pathlib.Path(__file__).parent.resolve().joinpath("signing_key.pem")
    dev_sigstruct = Sigstruct.from_enclave_file(signed_enclave)
    out = "/tmp/audit_enclave.signed.so"
    sgx_sign(unsigned_enclave, key=signing_key, out=out, config=enclave_config)
    auditor_sigstruct = Sigstruct.from_enclave_file(out)
    if not ias_report:
        print(
            f"\nsigned enclave NMRENCLAVE: \t\t{term.bold}{dev_sigstruct.mrenclave.hex()}{term.normal}"
        )
        print(
            f"built-from-source enclave NMRENCLAVE: \t{term.bold}{auditor_sigstruct.mrenclave.hex()}{term.normal}\n"
        )
        if auditor_sigstruct.mrenclave == dev_sigstruct.mrenclave:
            print(f"{term.green}MRENCLAVE match!{term.normal}")
        else:
            print(f"{term.red}MRENCLAVE do not match!{term.normal}")
        return auditor_sigstruct.mrenclave == dev_sigstruct.mrenclave

    raise NotImplementedError


def verify(
    signed_enclave,
    unsigned_enclave,
    enclave_config,
    signing_key=None,
    show_mrsigner=False,
    verbose=True,
):
    """Sign the enclave_so, and compare with the signed_enclave.

    :param str signed_enclave: The signed enclave to check against.
    :param str unsigned_enclave: The enclave to sign and verify
        against the signed enclave.
    :param str enclave_config: The enclave configuration used to sign
        the enclave.
    :param str signing_key: The private key used to sign the enclave.
    :param bool show_mrsigner: Whether to show the mrsigner field or not.
        Defaults to ``False``.
    :param bool verbose: Whether to use verbose mode or not.
        Defaults to ``True``.
    """
    if not signing_key:
        signing_key = (
            pathlib.Path(__file__).parent.resolve().joinpath("signing_key.pem")
        )
    dev_sigstruct = Sigstruct.from_enclave_file(signed_enclave)
    out = "/tmp/audit_enclave.signed.so"
    sgx_sign(unsigned_enclave, key=signing_key, out=out, config=enclave_config)
    auditor_sigstruct = Sigstruct.from_enclave_file(out)
    report_data = {
        attr: ReportItem(
            matches=val,
            expected=getattr(dev_sigstruct, attr),
            computed=getattr(auditor_sigstruct, attr),
        )
        for attr, val in auditor_sigstruct.cmp(dev_sigstruct).items()
    }
    report = ReproducibilityReport(**report_data)
    if verbose:
        print_report(report, show_mrsigner=show_mrsigner)
    return report


def print_report(report, show_mrsigner=False):
    print(f"\n{term.bold}Reproducibility Report\n----------------------")
    for attr, val in report._asdict().items():
        if attr == "mrsigner" and not show_mrsigner:
            continue
        print(f"{term.bold}{attr}:{term.normal}")
        for k, v in val._asdict().items():
            if attr in ("mrenclave", "mrsigner") and k in ("expected", "computed"):
                v = v.hex()
            print(f"   {k}: ", end="")
            if k == "matches":
                if v:
                    matches = True
                    print(f"{term.green}{v}{term.normal}")
                else:
                    matches = False
                    print(f"{term.red}{v}{term.normal}")
            else:
                if not matches and k == "computed":
                    print(f"{term.red}{v}{term.normal}")
                else:
                    print(f"{v}")
