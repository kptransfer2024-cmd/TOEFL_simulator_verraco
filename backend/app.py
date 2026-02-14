from fastapi import FastAPI
from routes.exam_routes import router as exam_router

app = FastAPI(title="verraco MVP")
app.include_router(exam_router)
