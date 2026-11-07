// Native unit audit only. The header is extracted unchanged from verified Open3D source.
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include "boundary_frame_excerpt.h"

template <typename T>
int CheckFrame(const std::array<double, 3>& input) {
    const double norm = std::sqrt(input[0] * input[0] + input[1] * input[1] +
                                  input[2] * input[2]);
    T n[3], u[3], v[3];
    for (int i = 0; i < 3; ++i) n[i] = static_cast<T>(input[i] / norm);
    open3d::GetCoordinateSystemOnPlane(n, u, v);
    double uu = 0, vv = 0, uv = 0, un = 0, vn = 0;
    for (int i = 0; i < 3; ++i) {
        if (!std::isfinite(u[i]) || !std::isfinite(v[i])) return 1;
        uu += u[i] * u[i];
        vv += v[i] * v[i];
        uv += u[i] * v[i];
        un += u[i] * n[i];
        vn += v[i] * n[i];
    }
    const double tolerance = 16 * std::numeric_limits<T>::epsilon();
    return (std::abs(uu - 1) > tolerance || std::abs(vv - 1) > tolerance ||
            std::abs(uv) > tolerance || std::abs(un) > tolerance ||
            std::abs(vn) > tolerance) ? 1 : 0;
}

int main() {
    int cases = 0, failed = 0;
    for (int x = -1; x <= 1; ++x) {
        for (int y = -1; y <= 1; ++y) {
            for (int z = -1; z <= 1; ++z) {
                if (x == 0 && y == 0 && z == 0) continue;
                std::array<double, 3> n = {double(x), double(y), double(z)};
                failed += CheckFrame<float>(n) + CheckFrame<double>(n);
                cases += 2;
            }
        }
    }
    for (double epsilon : {1e-12, 1e-8, 1e-5}) {
        for (double sign : {-1.0, 1.0}) {
            std::array<double, 3> n = {epsilon, -epsilon, sign};
            failed += CheckFrame<float>(n) + CheckFrame<double>(n);
            cases += 2;
        }
    }
    std::cout << "{\"cases\":" << cases << ",\"failed\":" << failed << "}\n";
    return failed ? 1 : 0;
}
