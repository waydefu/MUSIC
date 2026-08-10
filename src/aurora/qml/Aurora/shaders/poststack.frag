#version 440

// 電影感疊加層：暗角 + 底片顆粒 + 掃描線。
//
// 刻意設計成「不取樣底下的場景」—— 這樣就不需要把整個畫面先渲染到
// 一張離屏貼圖再處理，省下一個全螢幕的 render target 與頻寬。
// 需要取樣場景的效果（色散）另外掛在內容層，只在電影畫質下啟用。
//
// 輸出採預乘 alpha，這是 Qt Quick 場景圖的慣例。

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;        // 秒，驅動顆粒的抖動
    float vignette;    // 暗角強度 0..1
    float grain;       // 顆粒強度 0..1
    float scanline;    // 掃描線強度 0..1
    float pulse;       // 低頻能量 0..1，讓暗角隨鼓點收縮
    vec4  tint;        // 主色，給暗角一點色偏而非死黑
};

// 便宜的二維雜湊。不需要高品質亂數，只要每幀不同、空間上不相關。
float hash(vec2 p) {
    p = fract(p * vec2(443.897, 441.423));
    p += dot(p, p.yx + 19.19);
    return fract((p.x + p.y) * p.x);
}

void main() {
    vec2 uv = qt_TexCoord0;

    // 暗角：橢圓形衰減，寬螢幕下上下邊比左右先暗，比正圓自然
    vec2 centered = uv - 0.5;
    float dist = length(centered * vec2(1.0, 0.94));
    float inner = 0.34 - pulse * 0.05;   // 鼓點時暗角往內收，畫面像被撞了一下
    float vig = smoothstep(inner, 0.88, dist) * vignette;

    // 底片顆粒：時間項讓它每幀重新分佈，靜態噪點看起來像髒掉的螢幕
    float n = hash(uv * 1024.0 + vec2(time * 91.7, time * 57.3)) - 0.5;
    float grainAlpha = abs(n) * grain;

    // 掃描線：極輕微，只是為了讓平面色塊多一點質地
    float scan = (sin(uv.y * 880.0) * 0.5 + 0.5) * scanline;

    float alpha = clamp(vig + grainAlpha + scan, 0.0, 1.0);
    if (alpha <= 0.0) {
        fragColor = vec4(0.0);
        return;
    }

    // 暗角帶一點主色色偏；顆粒是純黑白的亮暗點
    vec3 vignetteColour = mix(vec3(0.0), tint.rgb, 0.22) * 0.35;
    vec3 grainColour = vec3(step(0.0, n));

    vec3 colour = (vignetteColour * (vig + scan) + grainColour * grainAlpha)
                  / max(alpha, 1e-4);

    fragColor = vec4(colour * alpha, alpha) * qt_Opacity;
}
