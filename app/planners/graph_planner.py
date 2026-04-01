from typing import Dict, Iterable, List, Tuple

import networkx as nx


def load_route_graph(route_graph: Dict) -> nx.Graph:
    graph = nx.Graph()

    for node in route_graph.get("nodes", []):
        graph.add_node(
            node["node_id"],
            x=float(node["x"]),
            y=float(node["y"]),
            z=float(node.get("z", 0.0)),
        )

    for edge in route_graph.get("edges", []):
        graph.add_edge(
            edge["from"],
            edge["to"],
            edge_id=edge["edge_id"],
            weight=float(edge.get("cost", edge.get("length_m", 1.0))),
            length_m=float(edge.get("length_m", 1.0)),
            surface=edge.get("surface", "unknown"),
        )

    return graph


def nearest_graph_node(graph: nx.Graph, x: float, y: float) -> str:
    best_node_id = None
    best_distance = None
    for node_id, attr in graph.nodes(data=True):
        dx = float(attr["x"]) - x
        dy = float(attr["y"]) - y
        distance = dx * dx + dy * dy
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_node_id = node_id

    if best_node_id is None:
        raise ValueError("route_graph is empty")
    return best_node_id


def path_waypoints(graph: nx.Graph, node_path: Iterable[str]) -> List[Dict]:
    points = []
    for node_id in node_path:
        attr = graph.nodes[node_id]
        points.append(
            {
                "x": float(attr["x"]),
                "y": float(attr["y"]),
                "z": float(attr.get("z", 0.0)),
            }
        )
    return points


def shortest_path(graph: nx.Graph, start_xy: Tuple[float, float], goal_xy: Tuple[float, float]) -> Dict:
    start_node = nearest_graph_node(graph, start_xy[0], start_xy[1])
    goal_node = nearest_graph_node(graph, goal_xy[0], goal_xy[1])
    node_path = nx.shortest_path(graph, start_node, goal_node, weight="weight")
    length_m = float(nx.path_weight(graph, node_path, weight="length_m"))

    return {
        "start_node": start_node,
        "goal_node": goal_node,
        "node_path": list(node_path),
        "waypoints": path_waypoints(graph, node_path),
        "length_m": length_m,
    }
