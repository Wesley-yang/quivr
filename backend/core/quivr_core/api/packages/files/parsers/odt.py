from langchain_community.document_loaders import UnstructuredPDFLoader

from quivr_core.models.files import File

from .common import process_file


def process_odt(
    file: File, brain_id, original_file_name, integration=None, integration_link=None
):
    return process_file(
        file=file,
        loader_class=UnstructuredPDFLoader,
        brain_id=brain_id,
        original_file_name=original_file_name,
        integration=integration,
        integration_link=integration_link,
    )
