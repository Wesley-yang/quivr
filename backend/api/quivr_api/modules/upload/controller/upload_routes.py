import io
import os
from typing import Annotated, Optional
from uuid import UUID

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException, Query,
                     UploadFile)
from quivr_api.celery_config import celery
from quivr_api.logger import get_logger
from quivr_api.middlewares.auth import AuthBearer, get_current_user
from quivr_api.models.settings import get_supabase_async_client
from quivr_api.modules.brain.entity.brain_entity import RoleEnum
from quivr_api.modules.brain.service.brain_authorization_service import \
    validate_brain_authorization
from quivr_api.modules.dependencies import get_service
from quivr_api.modules.knowledge.dto.inputs import CreateKnowledgeProperties
from quivr_api.modules.knowledge.service.knowledge_service import \
    KnowledgeService
from quivr_api.modules.notification.dto.inputs import (
    CreateNotification, NotificationUpdatableProperties)
from quivr_api.modules.notification.entity.notification import \
    NotificationsStatusEnum
from quivr_api.modules.notification.service.notification_service import \
    NotificationService
from quivr_api.modules.upload.service.upload_file import upload_file_storage
from quivr_api.modules.user.entity.user_identity import UserIdentity
from quivr_api.modules.user.service.user_usage import UserUsage
from quivr_api.utils.byte_size import convert_bytes
from quivr_api.utils.telemetry import maybe_send_telemetry
from supabase.client import AsyncClient

logger = get_logger(__name__)
upload_router = APIRouter()

notification_service = NotificationService()
#knowledge_service = KnowledgeService()
knowledge_service = get_service(KnowledgeService)()

AsyncClientDep = Annotated[AsyncClient, Depends(get_supabase_async_client)]


@upload_router.post("/upload", dependencies=[Depends(AuthBearer())], tags=["Upload"])
async def upload_file(
    uploadFile: UploadFile,
    client: AsyncClientDep,
    background_tasks: BackgroundTasks,
    bulk_id: Optional[UUID] = Query(None, description="The ID of the bulk upload"),
    brain_id: UUID = Query(..., description="The ID of the brain"),
    chat_id: Optional[UUID] = Query(None, description="The ID of the chat"),
    current_user: UserIdentity = Depends(get_current_user),
    integration: Optional[str] = None,
    integration_link: Optional[str] = None,
):
    validate_brain_authorization(
        brain_id, current_user.id, [RoleEnum.Editor, RoleEnum.Owner]
    )
    user_daily_usage = UserUsage(
        id=current_user.id,
        email=current_user.email,
    )
    user_settings = user_daily_usage.get_user_settings()
    remaining_free_space = user_settings.get("max_brain_size", 1 << 30)  # 1GB
    if remaining_free_space - uploadFile.size < 0:
        message = f"Brain will exceed maximum capacity. Maximum file allowed is : {convert_bytes(remaining_free_space)}"
        raise HTTPException(status_code=403, detail=message)

    # TODO:  Later
    upload_notification = notification_service.add_notification(
        CreateNotification(
            user_id=current_user.id,
            bulk_id=bulk_id,
            status=NotificationsStatusEnum.INFO,
            title=f"{uploadFile.filename}",
            category="upload",
            brain_id=str(brain_id),
        )
    )

    background_tasks.add_task(
        maybe_send_telemetry, "upload_file", {"file_name": uploadFile.filename}
    )

    filename_with_brain_id = str(brain_id) + "/" + str(uploadFile.filename)
    try:
        # NOTE(@aminediro) : This should redone. The supabase storage client interface is badly designed
        # It specifically checks for BufferedReader | bytes before sending
        # TODO: We bypass this to write to S3 Storage directly
        buff_reader = io.BufferedReader(uploadFile.file)  # type: ignore
        await upload_file_storage(client, buff_reader, filename_with_brain_id)
    except FileExistsError:
        notification_service.update_notification_by_id(
            upload_notification.id if upload_notification else None,
            NotificationUpdatableProperties(
                status=NotificationsStatusEnum.ERROR,
                description=f"File {uploadFile.filename} already exists in storage.",
            ),
        )
        raise HTTPException(
            status_code=403,
            detail=f"File {uploadFile.filename} already exists in storage.",
        )
    except Exception as e:
        logger.exception(f"Exception in upload_route {e}")
        notification_service.update_notification_by_id(
            upload_notification.id if upload_notification else None,
            NotificationUpdatableProperties(
                status=NotificationsStatusEnum.ERROR,
                description="There was an error uploading the file",
            ),
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to upload file to storage. {e}"
        )
    #FIXME: @chloedia check if these are the correct properties
    knowledge_to_add = CreateKnowledgeProperties(
        brain_id=brain_id,
        file_name=uploadFile.filename,
        mime_type=os.path.splitext(
            uploadFile.filename  # pyright: ignore reportPrivateUsage=none
        )[-1].lower(),
        source=integration,
        source_link=integration_link,
        file_size=uploadFile.size,
    )

    knowledge = await knowledge_service.add_knowledge(knowledge_to_add)

    celery.send_task(
        "process_file_task",
        kwargs={
            "file_name": filename_with_brain_id,
            "file_original_name": uploadFile.filename,
            "brain_id": brain_id,
            "notification_id": upload_notification.id,
            "knowledge_id": knowledge.id,
            "integration": integration,
            "integration_link": integration_link,
        },
    )
    return {"message": "File processing has started."}
