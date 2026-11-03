from pathlib import Path
from langgraph_four_node_workflow import build_graph

workflow = build_graph()
png_data = workflow.get_graph().draw_mermaid_png()
Path("langgraph_workflow.png").write_bytes(png_data)