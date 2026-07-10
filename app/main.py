from fastapi import APIRouter
from fastapi import FastAPI

app = FastAPI()
router = APIRouter(prefix="/api/v1",tags=["/api/v1"])
app.include_router(router)


def main():
    pass


    


if __name__ == "__main__":
    main()
