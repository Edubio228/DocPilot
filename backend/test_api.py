"""Test script for DocPilot API"""
import httpx
import asyncio

async def test_health():
    """Test the health endpoint"""
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/api/health")
        print("=== Health Check ===")
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
        return resp.status_code == 200

async def test_summarize():
    """Test the summarize endpoint"""
    payload = {
        "page_url": "https://example.com/test",
        "page_text": """# Introduction to Python

Python is a popular programming language created by Guido van Rossum in 1991. 
It is known for its simplicity and readability.

## Key Features

- Easy to learn and use
- Supports multiple programming paradigms
- Large standard library
- Active community and ecosystem

## Use Cases

Python is widely used in:
- Web development
- Data science
- Machine learning
- Automation
""",
        "page_title": "Introduction to Python"
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("\n=== Summarize Test ===")
        resp = await client.post(
            "http://localhost:8000/api/summarize",
            json=payload
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Page Type: {data.get('page_type')}")
            print(f"Summary: {data.get('summary', '')[:200]}...")
        else:
            print(f"Error: {resp.text}")
        return resp.status_code == 200

async def main():
    print("Testing DocPilot API...\n")
    
    # Test health
    health_ok = await test_health()
    
    if health_ok:
        # Test summarize
        await test_summarize()
    else:
        print("Health check failed, skipping other tests")

if __name__ == "__main__":
    asyncio.run(main())
