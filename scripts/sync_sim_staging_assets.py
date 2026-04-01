#!/usr/bin/env python3
import json
import math
from collections import defaultdict
from heapq import heappop, heappush
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSET_ROOT = ROOT_DIR / 'data' / 'assets' / 'ncepu'
MISSION_DIR = ASSET_ROOT / 'mission'
FLEET_DIR = ASSET_ROOT / 'fleet'
PLANNING_ASSETS_DIR = ASSET_ROOT / 'planning' / 'assets'

ROUTE_GRAPH_PATH = MISSION_DIR / 'route_graph.json'
NAV_POINTS_PATH = MISSION_DIR / 'nav_points_enriched.geojson'
NAV_BINDINGS_PATH = MISSION_DIR / 'nav_point_bindings.json'
SEMANTIC_CATALOG_PATH = MISSION_DIR / 'semantic_catalog.json'
ROBOT_REGISTRY_PATH = FLEET_DIR / 'robot_registry.json'
NAV_TO_NAV_OUTPUT = PLANNING_ASSETS_DIR / 'nav_to_nav_shortest_paths.json'
ROBOT_TO_NAV_OUTPUT = PLANNING_ASSETS_DIR / 'robot_to_nav_costs.json'
PLANNER_PROBLEM_OUTPUT = PLANNING_ASSETS_DIR / 'planner_problem.json'

SIM_STAGING = {
    'slot_01': {
        'x': -388.6481733084797,
        'z': -238.13407919503143,
        'heading': -0.14427055095580824,
        'note': 'Simulation staging pose moved just outside 教12B on a collision-free exterior point.',
    },
    'slot_02': {
        'x': 404.462,
        'z': 267.59,
        'heading': -1.8640778386708292,
        'note': 'Simulation staging pose aligned with the north-gate departure direction into campus.',
    },
    'slot_03': {
        'x': -50.856,
        'z': -362.015,
        'heading': 1.4254752358431546,
        'note': 'Simulation staging pose aligned with the south-gate departure direction into campus.',
    },
}

def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def relative_ref(path: Path) -> str:
    return path.resolve().relative_to(ASSET_ROOT.resolve()).as_posix()

def dijkstra(adjacency, source_node_id):
    dist = {source_node_id: 0.0}
    prev_node = {}
    prev_edge = {}
    heap = [(0.0, source_node_id)]
    while heap:
        current_dist, node_id = heappop(heap)
        if current_dist > dist.get(node_id, math.inf) + 1e-9:
            continue
        for edge in adjacency[node_id]:
            nxt = edge['to_node_id']
            nd = current_dist + edge['dog_cost']
            old_dist = dist.get(nxt, math.inf)
            if nd + 1e-9 < old_dist:
                dist[nxt] = nd
                prev_node[nxt] = node_id
                prev_edge[nxt] = edge['edge_id']
                heappush(heap, (nd, nxt))
    return dist, prev_node, prev_edge

def reconstruct_path(prev_node, prev_edge, source_node_id, target_node_id):
    if source_node_id == target_node_id:
        return [source_node_id], []
    if target_node_id not in prev_node:
        return [], []
    nodes = [target_node_id]
    edges = []
    cursor = target_node_id
    while cursor != source_node_id:
        edges.append(prev_edge[cursor])
        cursor = prev_node[cursor]
        nodes.append(cursor)
    nodes.reverse()
    edges.reverse()
    return nodes, edges

def euclidean_distance(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)

def build_nav_anchor(bindings, nav_features):
    nav_anchor = {}
    nav_features_by_id = {feature['properties']['id']: feature for feature in nav_features['features']}
    for binding in bindings['bindings']:
        node = binding['nearest_node']
        nav_id = binding['nav_point_id']
        feature = nav_features_by_id[nav_id]
        props = feature['properties']
        nav_anchor[nav_id] = {
            'nav_point_id': nav_id,
            'nav_point_name': binding['nav_point_name'],
            'graph_node_id': node['node_id'],
            'access_distance_m': round(float(node['distance_m']), 3),
            'graph_node_local_m': {'x': float(node['local_x']), 'z': float(node['local_z'])},
            'nav_local_m': {'x': float(binding['local_x']), 'z': float(binding['local_z'])},
            'lat': float(binding['lat']),
            'lon': float(binding['lon']),
            'category': binding.get('category', ''),
            'semantic_type': binding.get('semantic_type', ''),
            'building_ref': binding.get('building_ref', ''),
            'building_name': binding.get('building_name', ''),
            'allowed_robot_types': props.get('robot_types', ['dog']),
            'yaw': props.get('yaw', 0),
            'note': props.get('note', ''),
            'recommended_anchor_type': binding.get('recommended_anchor_type', 'node'),
        }
    return nav_anchor

def update_robot_registry(robot_registry):
    for robot in robot_registry['robots']:
        slot = robot['planning_slot_id']
        staging = SIM_STAGING[slot]
        anchor = robot['start_pose']['anchor_local_m']
        offset = {
            'x': round(float(staging['x']) - float(anchor['x']), 6),
            'z': round(float(staging['z']) - float(anchor['z']), 6),
        }
        for phase in ('start_pose', 'home_pose'):
            robot[phase]['offset_from_anchor_local_m'] = dict(offset)
            robot[phase]['resolved_local_position_m'] = {
                'x': float(staging['x']),
                'z': float(staging['z']),
            }
            robot[phase]['heading_rad'] = float(staging['heading'])
        robot['start_pose']['note'] = staging['note']
        robot['planner_limits']['max_cruise_speed_mps'] = 1.0
    return robot_registry

def build_robot_anchor(robot_registry, nav_anchor):
    robot_start = {}
    robot_home = {}
    for robot in robot_registry['robots']:
        robot_id = robot['planning_slot_id']
        for phase, container in [('start', robot_start), ('home', robot_home)]:
            phase_pose = robot[f'{phase}_pose']
            anchor_nav_id = phase_pose['anchor_nav_point_id']
            anchor = nav_anchor[anchor_nav_id]
            resolved = phase_pose['resolved_local_position_m']
            node_local = anchor['graph_node_local_m']
            access_distance = euclidean_distance(
                float(resolved['x']), float(resolved['z']),
                float(node_local['x']), float(node_local['z']),
            )
            container[robot_id] = {
                'planning_slot_id': robot_id,
                'hardware_id': robot['hardware_id'],
                'anchor_nav_point_id': anchor_nav_id,
                'anchor_nav_point_name': anchor['nav_point_name'],
                'graph_node_id': anchor['graph_node_id'],
                'resolved_local_position_m': {'x': float(resolved['x']), 'z': float(resolved['z'])},
                'heading_rad': float(phase_pose.get('heading_rad', 0.0)),
                'access_distance_m': round(access_distance, 3),
                'cruise_speed_mps': float(robot['planner_limits']['max_cruise_speed_mps']),
                'yaw_rate_rad_per_s': float(robot['planner_limits']['max_yaw_rate_rad_per_s']),
            }
    return robot_start, robot_home

def build_pairwise_nav_costs(nav_anchor, adjacency, planning_speed_mps):
    nav_ids = sorted(nav_anchor.keys())
    pair_map = {}
    anchor_export = {}
    for nav_id in nav_ids:
        source_anchor = nav_anchor[nav_id]
        anchor_export[nav_id] = source_anchor
        source_node = source_anchor['graph_node_id']
        dist, prev_node, prev_edge = dijkstra(adjacency, source_node)
        pair_map[nav_id] = {}
        for target_id in nav_ids:
            target_anchor = nav_anchor[target_id]
            if nav_id == target_id:
                pair_map[nav_id][target_id] = {
                    'reachable': True,
                    'distance_m': 0.0,
                    'estimated_time_s': 0.0,
                    'graph_distance_m': 0.0,
                    'graph_time_s': 0.0,
                    'source_access_distance_m': 0.0,
                    'target_access_distance_m': 0.0,
                    'path_node_ids': [source_node],
                    'path_edge_ids': [],
                }
                continue
            target_node = target_anchor['graph_node_id']
            if target_node not in dist:
                pair_map[nav_id][target_id] = {
                    'reachable': False,
                    'distance_m': None,
                    'estimated_time_s': None,
                    'graph_distance_m': None,
                    'graph_time_s': None,
                    'source_access_distance_m': source_anchor['access_distance_m'],
                    'target_access_distance_m': target_anchor['access_distance_m'],
                    'path_node_ids': [],
                    'path_edge_ids': [],
                }
                continue
            path_nodes, path_edges = reconstruct_path(prev_node, prev_edge, source_node, target_node)
            total_distance = source_anchor['access_distance_m'] + dist[target_node] + target_anchor['access_distance_m']
            pair_map[nav_id][target_id] = {
                'reachable': True,
                'distance_m': round(total_distance, 3),
                'estimated_time_s': round(total_distance / planning_speed_mps, 3),
                'graph_distance_m': round(dist[target_node], 3),
                'graph_time_s': round(dist[target_node] / planning_speed_mps, 3),
                'source_access_distance_m': source_anchor['access_distance_m'],
                'target_access_distance_m': target_anchor['access_distance_m'],
                'path_node_ids': path_nodes,
                'path_edge_ids': path_edges,
            }
    return {
        'schema_version': '1.0.0',
        'metadata': {
            'route_graph_ref': 'mission/route_graph.json',
            'nav_points_ref': 'mission/nav_points_enriched.geojson',
            'nav_bindings_ref': 'mission/nav_point_bindings.json',
            'access_model': 'nearest_graph_node_plus_local_access_distance',
            'planning_speed_mps': planning_speed_mps,
            'pair_count': sum(len(targets) for targets in pair_map.values()),
        },
        'nav_anchor_nodes': anchor_export,
        'pairs': pair_map,
    }

def build_robot_nav_costs(robot_start, robot_home, nav_anchor, adjacency):
    def compute_phase_costs(robot_phase):
        output = {}
        for robot_id, phase_info in robot_phase.items():
            source_node = phase_info['graph_node_id']
            dist, prev_node, prev_edge = dijkstra(adjacency, source_node)
            cruise_speed = phase_info['cruise_speed_mps']
            per_nav = {}
            for nav_id, target_anchor in nav_anchor.items():
                target_node = target_anchor['graph_node_id']
                if target_node not in dist:
                    per_nav[nav_id] = {
                        'reachable': False,
                        'distance_m': None,
                        'estimated_time_s': None,
                        'graph_distance_m': None,
                        'graph_time_s': None,
                        'source_access_distance_m': phase_info['access_distance_m'],
                        'target_access_distance_m': target_anchor['access_distance_m'],
                        'path_node_ids': [],
                        'path_edge_ids': [],
                    }
                    continue
                path_nodes, path_edges = reconstruct_path(prev_node, prev_edge, source_node, target_node)
                total_distance = phase_info['access_distance_m'] + dist[target_node] + target_anchor['access_distance_m']
                per_nav[nav_id] = {
                    'reachable': True,
                    'distance_m': round(total_distance, 3),
                    'estimated_time_s': round(total_distance / cruise_speed, 3),
                    'graph_distance_m': round(dist[target_node], 3),
                    'graph_time_s': round(dist[target_node] / cruise_speed, 3),
                    'source_access_distance_m': round(phase_info['access_distance_m'], 3),
                    'target_access_distance_m': target_anchor['access_distance_m'],
                    'path_node_ids': path_nodes,
                    'path_edge_ids': path_edges,
                }
            output[robot_id] = {'robot': phase_info, 'costs': per_nav}
        return output
    return {
        'schema_version': '1.0.0',
        'metadata': {
            'route_graph_ref': 'mission/route_graph.json',
            'nav_bindings_ref': 'mission/nav_point_bindings.json',
            'robot_registry_ref': 'fleet/robot_registry.json',
            'access_model': 'robot_offset_pose_to_anchor_node_plus_graph_path_plus_nav_access',
        },
        'start_to_nav_costs': compute_phase_costs(robot_start),
        'nav_to_home_costs': compute_phase_costs(robot_home),
    }

def build_planner_problem(robot_registry, nav_anchor, semantic_catalog):
    robots = []
    for robot in robot_registry['robots']:
        robots.append({
            'planning_slot_id': robot['planning_slot_id'],
            'hardware_id': robot['hardware_id'],
            'shared_model_ref': robot['shared_model_ref'],
            'start_nav_point_id': robot['start_nav_point_id'],
            'home_nav_point_id': robot['home_nav_point_id'],
            'start_pose': robot['start_pose'],
            'home_pose': robot['home_pose'],
            'planner_limits': robot['planner_limits'],
            'runtime_profile': robot['runtime_profile'],
            'ros_namespace': robot['ros_namespace'],
            'gazebo_entity_name': robot['gazebo_entity_name'],
        })
    nav_points = []
    for nav_id in sorted(nav_anchor.keys()):
        anchor = nav_anchor[nav_id]
        nav_points.append({
            'nav_point_id': nav_id,
            'name': anchor['nav_point_name'],
            'graph_node_id': anchor['graph_node_id'],
            'access_distance_m': anchor['access_distance_m'],
            'local_m': anchor['nav_local_m'],
            'lat': anchor['lat'],
            'lon': anchor['lon'],
            'category': anchor['category'],
            'semantic_type': anchor['semantic_type'],
            'building_ref': anchor['building_ref'],
            'building_name': anchor['building_name'],
            'allowed_robot_types': anchor['allowed_robot_types'],
        })
    target_set_ids = []
    target_sets_path = PLANNING_ASSETS_DIR / 'semantic_target_sets.json'
    if target_sets_path.exists():
        target_sets = load_json(target_sets_path)
        target_set_ids = [item['target_set_id'] for item in target_sets.get('target_sets', [])]
    return {
        'schema_version': '1.0.0',
        'problem_id': 'ncepu_multi_dog_planner_problem',
        'refs': {
            'planning_input_manifest': 'planning/assets/planning_input_manifest.json',
            'semantic_catalog': 'mission/semantic_catalog.json',
            'nav_points': 'mission/nav_points_enriched.geojson',
            'route_graph': 'mission/route_graph.json',
            'nav_bindings': 'mission/nav_point_bindings.json',
            'robot_registry': 'fleet/robot_registry.json',
            'target_sets': 'planning/assets/semantic_target_sets.json',
            'nav_to_nav_costs': 'planning/assets/nav_to_nav_shortest_paths.json',
            'robot_to_nav_costs': 'planning/assets/robot_to_nav_costs.json',
            'mission_templates': 'planning/assets/mission_request_templates.json',
        },
        'fleet': robot_registry['fleet'],
        'robots': robots,
        'nav_points': nav_points,
        'target_set_ids': target_set_ids,
        'default_objective': {
            'minimize_total_distance': True,
            'balance_robot_task_count': True,
            'respect_robot_range_budget': True,
            'return_home_after_completion': True,
        },
        'assumptions': [
            'All roads in route_graph.json are already normalized to bidirectional travel.',
            'Task points are injected into graph planning via nearest graph node plus local access distance.',
            'battery_capacity_Wh remains null; planning_range_budget_m is the planner-side surrogate budget.',
        ],
    }

def main():
    route_graph = load_json(ROUTE_GRAPH_PATH)
    nav_features = load_json(NAV_POINTS_PATH)
    nav_bindings = load_json(NAV_BINDINGS_PATH)
    semantic_catalog = load_json(SEMANTIC_CATALOG_PATH)
    robot_registry = load_json(ROBOT_REGISTRY_PATH)

    robot_registry = update_robot_registry(robot_registry)
    write_json(ROBOT_REGISTRY_PATH, robot_registry)

    adjacency = defaultdict(list)
    for edge in route_graph['edges']:
        adjacency[edge['from_node_id']].append(edge)

    nav_anchor = build_nav_anchor(nav_bindings, nav_features)
    robot_start, robot_home = build_robot_anchor(robot_registry, nav_anchor)

    nav_to_nav = build_pairwise_nav_costs(nav_anchor, adjacency, planning_speed_mps=1.0)
    robot_to_nav = build_robot_nav_costs(robot_start, robot_home, nav_anchor, adjacency)
    planner_problem = build_planner_problem(robot_registry, nav_anchor, semantic_catalog)

    write_json(NAV_TO_NAV_OUTPUT, nav_to_nav)
    write_json(ROBOT_TO_NAV_OUTPUT, robot_to_nav)
    write_json(PLANNER_PROBLEM_OUTPUT, planner_problem)

    print(json.dumps({
        'robot_registry': str(ROBOT_REGISTRY_PATH),
        'planner_problem': str(PLANNER_PROBLEM_OUTPUT),
        'robot_to_nav_costs': str(ROBOT_TO_NAV_OUTPUT),
        'nav_to_nav_costs': str(NAV_TO_NAV_OUTPUT),
        'sim_staging': SIM_STAGING,
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
