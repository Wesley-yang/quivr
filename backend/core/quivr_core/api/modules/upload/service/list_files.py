from multiprocessing import get_logger

from supabase.client import Client

from quivr_core.api.models.settings import get_supabase_client

logger = get_logger()


def list_files_from_storage(path):
    supabase_client: Client = get_supabase_client()

    try:
        response = supabase_client.storage.from_("quivr").list(path)
        return response
    except Exception as e:
        logger.error(e)
