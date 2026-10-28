"""Keep historical experiment adapters in source control, outside distributions."""
from setuptools.command.build_py import build_py

# These modules import experiments and are outside the independent formal core.
HISTORICAL=frozenset({'a2_snapshot','bootstrap','chroma_store','retrieval','tracing'})


class FormalBuildPy(build_py):
    def find_package_modules(self,package,package_dir):
        modules=super().find_package_modules(package,package_dir)
        return [item for item in modules if package!='naiyue_rag' or item[1] not in HISTORICAL]
