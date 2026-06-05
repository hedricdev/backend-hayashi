from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def importar():
    # TODO: Task 07
    return {"status": "ok", "message": "não implementado"}
