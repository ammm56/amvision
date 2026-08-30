export type ImageRefSampleTransportKind = 'storage' | 'local-path'

/** 按公开 payload 类型构造可直接编辑并提交的 Runtime 输入示例。 */
export function buildWorkflowRuntimeInputSample(
  payloadTypeId: string,
  bindingId: string,
  imageRefTransportKind: ImageRefSampleTransportKind,
): unknown {
  if (bindingId.includes('deployment_request')) {
    return { request_id: 'manual-test', source: 'web-ui' }
  }
  if (payloadTypeId === 'image-ref.v1') {
    if (imageRefTransportKind === 'local-path') {
      return {
        transport_kind: 'local-path',
        local_path: 'C:\\vision\\inputs\\sample.png',
        media_type: 'image/png',
      }
    }
    return {
      transport_kind: 'storage',
      object_key: 'workflows/inputs/sample.png',
      media_type: 'image/png',
    }
  }
  if (payloadTypeId === 'image-base64.v1') {
    return {
      image_base64: '<base64>',
      media_type: 'image/png',
    }
  }
  if (payloadTypeId === 'points.v1') {
    return {
      coordinate_space: 'source-image-pixels',
      unit: 'pixel',
      count: 2,
      items: [
        { point_id: 'point-1', point_index: 0, xy: [100, 100] },
        { point_id: 'point-2', point_index: 1, xy: [500, 100] },
      ],
    }
  }
  if (payloadTypeId === 'contours.v1') {
    return {
      count: 1,
      items: [{
        contour_index: 1,
        point_count: 4,
        bbox_xyxy: [100, 100, 501, 401],
        points: [[100, 100], [500, 100], [500, 400], [100, 400]],
      }],
    }
  }
  if (payloadTypeId === 'camera-calibration.v1') {
    return buildCameraCalibrationSample('replace-camera-calibration-id')
  }
  if (payloadTypeId === 'lines.v1') {
    return {
      coordinate_space: 'source-image-pixels',
      unit: 'pixel',
      count: 1,
      items: [{
        line_index: 0,
        start_xy: [100, 100],
        end_xy: [500, 100],
        length_pixels: 400,
        angle_deg: 0,
      }],
    }
  }
  if (payloadTypeId === 'circles.v1') {
    return {
      coordinate_space: 'source-image-pixels',
      unit: 'pixel',
      count: 1,
      items: [{
        circle_index: 0,
        center_xy: [320, 240],
        radius: 100,
        diameter: 200,
        area: 31415.926,
      }],
    }
  }
  if (payloadTypeId === 'ellipses.v1') {
    return {
      coordinate_space: 'source-image-pixels',
      unit: 'pixel',
      count: 1,
      items: [{
        ellipse_index: 0,
        center_xy: [320, 240],
        major_axis: 200,
        minor_axis: 100,
        angle_deg: 0,
        area: 15707.963,
      }],
    }
  }
  if (payloadTypeId === 'measurements.v1') {
    return {
      coordinate_space: 'source-image-pixels',
      unit: 'pixel',
      count: 1,
      items: [{
        measurement_id: 'measurement-1',
        measurement_kind: 'distance',
        coordinate_space: 'source-image-pixels',
        unit: 'pixel',
        values: { distance: 100 },
      }],
    }
  }
  if (payloadTypeId === 'regions.v1') {
    return {
      count: 1,
      items: [{
        region_id: 'region-1',
        score: 1,
        class_id: 0,
        class_name: 'target',
        bbox_xyxy: [100, 100, 500, 400],
        polygon_xy: [[100, 100], [500, 100], [500, 400], [100, 400]],
        area: 120000,
      }],
    }
  }
  if (payloadTypeId === 'planar-transform.v1') {
    return buildIdentityTransformSample()
  }
  if (payloadTypeId === 'localizations.v1') {
    return {
      coordinate_space: 'source-image-pixels',
      angle_unit: 'degrees',
      count: 1,
      items: [{
        localization_id: 'localization-1',
        method: 'feature',
        center_xy: [320, 240],
        angle_degrees: 0,
        scale: 1,
        score: 1,
        transform: buildIdentityTransformSample(),
      }],
    }
  }
  if (payloadTypeId === 'stereo-calibration.v1') {
    return {
      stereo_calibration_id: 'replace-stereo-calibration-id',
      left_camera: buildCameraCalibrationSample('left-camera'),
      right_camera: buildCameraCalibrationSample('right-camera'),
      image_size: [640, 480],
      left_coordinate_space: 'left-image-pixels',
      right_coordinate_space: 'right-image-pixels',
      rotation_3x3: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
      translation_3: [100, 0, 0],
      essential_matrix_3x3: [[0, 0, 0], [0, 0, -100], [0, 100, 0]],
      fundamental_matrix_3x3: [[0, 0, 0], [0, 0, -0.001], [0, 0.001, 0]],
      rms_epipolar_error: 0,
      source_fingerprint: 'replace-source-fingerprint',
      diagnostics: {},
    }
  }
  if (payloadTypeId.includes('boolean')) return false
  if (payloadTypeId.includes('number') || payloadTypeId.includes('float') || payloadTypeId.includes('integer')) return 0
  if (payloadTypeId.includes('object') || payloadTypeId.includes('json')) return {}
  if (payloadTypeId.includes('array') || payloadTypeId.includes('list')) return []
  return ''
}

function buildCameraCalibrationSample(calibrationId: string): Record<string, unknown> {
  return {
    calibration_id: calibrationId,
    camera_model: 'pinhole',
    image_size: [640, 480],
    camera_matrix: [[800, 0, 320], [0, 800, 240], [0, 0, 1]],
    distortion_coefficients: [0, 0, 0, 0, 0],
    image_coordinate_space: 'source-image-pixels',
    camera_coordinate_space: 'camera',
    object_point_unit: 'millimeter',
    observation_count: 1,
    rms_reprojection_error: 0,
    source_fingerprint: 'replace-source-fingerprint',
    diagnostics: {},
  }
}

function buildIdentityTransformSample(): Record<string, unknown> {
  return {
    transform_kind: 'homography',
    source_coordinate_space: 'reference-image-pixels',
    target_coordinate_space: 'source-image-pixels',
    matrix_3x3: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    match_count: 4,
    inlier_count: 4,
    inlier_match_ids: ['match-1', 'match-2', 'match-3', 'match-4'],
  }
}
