import os
import tempfile

# antes de importar o app: banco e dados num diretório temporário
os.environ.setdefault("MDC_DATA_DIR", tempfile.mkdtemp(prefix="mdc-test-"))
