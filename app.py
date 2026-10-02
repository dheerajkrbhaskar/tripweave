from pathlib import Path
import traceback
import uvicorn

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend import resume_travel_agent, run_travel_agent

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(
    title="Tripweave",
    description="Multi Agent Travel Planner",
    version="1.0.0"
)
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)
class TravelRequest(BaseModel):
    message: str = ""
    thread_id: str | None = None
    approved: bool | None = None
    feedback: str = ""

@app.get("/",response_class=HTMLResponse)
async def home(request:Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )

@app.post("/api/travel")
def travel_planner(request_data: TravelRequest):
    try:
        user_message = request_data.message.strip()
        if request_data.approved is None and not user_message:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error":"Message cannot be empty."
                }
            )
            
        if request_data.approved is None:
            result = run_travel_agent(user_message, request_data.thread_id)
        else:
            if not request_data.thread_id:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "thread_id is required to resume approval."},
                )
            result = resume_travel_agent(
                request_data.thread_id,
                request_data.approved,
                request_data.feedback,
            )
        return JSONResponse(
            content={
                "success": True,
                **result,
            }
        )
    except Exception as error:
        print("ERROR:", error)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "We couldn't complete your travel plan right now. Please try again in a moment."
            }
        )
    
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "message": "Tripweave travel planner API is running"
    }


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")



if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )