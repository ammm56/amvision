"""Decode All Retail Barcodes 节点实现。"""

from __future__ import annotations

from custom_nodes.barcode_protocol_nodes.backend.support import build_decode_handler


NODE_TYPE_ID = "custom.barcode.all-retail-decode"


NODE_DEFINITION_PAYLOAD = {'format_id': 'amvision.node-definition.v1',
 'node_type_id': 'custom.barcode.all-retail-decode',
 'display_name': 'Decode All Retail Barcodes',
 'category': 'barcode.decode',
 'description': '扫描输入图片中的全部零售条码制式，适合 EAN、UPC、DataBar 等零售识读场景。',
 'implementation_kind': 'custom-node',
 'runtime_kind': 'python-callable',
 'input_ports': [{'name': 'image', 'display_name': 'Image', 'payload_type_id': 'image-ref.v1'}],
 'output_ports': [{'name': 'results',
                   'display_name': 'Results',
                   'payload_type_id': 'barcode-results.v1'}],
 'parameter_schema': {'type': 'object',
                      'properties': {'try_rotate': {'type': 'boolean'},
                                     'try_downscale': {'type': 'boolean'},
                                     'try_invert': {'type': 'boolean'},
                                     'is_pure': {'type': 'boolean'},
                                     'return_errors': {'type': 'boolean'},
                                     'text_mode': {'type': 'string',
                                                   'enum': ['plain',
                                                            'hri',
                                                            'escaped',
                                                            'hex',
                                                            'eci',
                                                            'hex-eci']},
                                     'binarizer': {'type': 'string',
                                                   'enum': ['local-average',
                                                            'global-histogram',
                                                            'fixed-threshold',
                                                            'bool-cast']},
                                     'ean_add_on_symbol': {'type': 'string',
                                                           'enum': ['ignore', 'read', 'require']}}},
 'capability_tags': ['barcode.decode', 'barcode.all-retail'],
 'runtime_requirements': {'python_packages': ['opencv-python', 'numpy', 'zxing-cpp']},
 'node_pack_id': 'barcode.protocol-nodes',
 'node_pack_version': '0.1.0',
 'metadata': {'family': 'retail',
              'variant': 'all-retail',
              'scope_kind': 'group',
              'format_member_name': 'AllRetail'}}


handle_node = build_decode_handler(format_member_name="AllRetail", requested_format="All Retail")
