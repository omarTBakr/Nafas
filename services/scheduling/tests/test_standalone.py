import subprocess
import sys


def test_the_models_load_without_any_other_service():
    """
    A service must run on its own code alone. An ORM ForeignKey to identity's
    tables would fail here, in a process that has imported nothing else, even
    though the suite (which imports identity too) would never notice.
    """
    probe = (
        "import nafas_scheduling.models as m\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "m.Base.metadata.sorted_tables\n"
        "import sys; assert not any(name.startswith('nafas_identity') for name in sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
