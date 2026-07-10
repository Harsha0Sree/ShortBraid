from fastapi import FastAPI

app = FastAPI()


def main():
    pass

@app.get("/api/v1/ingest")
def upload():
    


if __name__ == "__main__":
    main()
