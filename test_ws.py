import asyncio
import websockets
import json

async def test_ws():
    # Login to get token first
    import urllib.request
    import uuid
    email = f"test_{uuid.uuid4().hex[:6]}@example.com"
    req = urllib.request.Request(
        "http://localhost:8000/api/auth/signup",
        data=json.dumps({"email": email, "username": "testws", "password": "password"}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    # create the user if not exists? we don't know the password
    # wait, the subagent created test_b
    # Let me just login
    try:
        response = urllib.request.urlopen(req)
        data = json.loads(response.read())
        token = data['access_token']
        print("Logged in, token:", token)
    except Exception as e:
        print("Login failed:", e)
        return

    uri = f"ws://localhost:8000/ws?token={token}"
    print("Connecting to ws...")
    try:
        async with websockets.connect(uri) as ws:
            print("Connected!")
            await ws.send(json.dumps({
                "type": "message",
                "to": "test_a_id", 
                "content": "Hello"
            }))
            res = await ws.recv()
            print("Received:", res)
    except Exception as e:
        print("WS Connection failed:", type(e), e)

asyncio.run(test_ws())
