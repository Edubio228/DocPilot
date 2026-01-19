"""Debug script for DocPilot summarization"""
import asyncio
import traceback
import sys

# Add the backend to path
sys.path.insert(0, "c:/Users/Acer/DocPilot/backend")

async def test_summarize():
    print("Testing summarization...")
    
    try:
        from app.agent.graph import SummarizationAgent, create_initial_state
        from app.agent.state import AgentState
        
        print("Imports successful")
        
        agent = SummarizationAgent()
        print("Agent created")
        
        result = await agent.summarize_page(
            page_url="https://example.com",
            page_text="""Python is a popular programming language created by Guido van Rossum in 1991. 
            It is known for its simplicity and readability. 
            Python supports multiple programming paradigms including procedural, object-oriented, and functional programming. 
            It has a large standard library and an active community.""",
            page_title="Python Overview"
        )
        
        print(f"Result type: {type(result)}")
        print(f"Page type: {result.page_type}")
        print(f"Final summary: {result.final_summary[:200] if result.final_summary else 'None'}...")
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_summarize())
