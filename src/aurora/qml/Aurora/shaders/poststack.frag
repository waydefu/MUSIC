#version 440

// 電影感疊加層：暗角 + 底片顆粒。
//
// 刻意設計成「不取樣底下的場景」—— 這樣就不需要把整個畫面先渲染到
// 一張離屏貼圖再處理，省下一個全螢幕的 render target 與頻寬。
// 需要取樣場景的效果（色散）另外掛在內容層，只在電影畫質下啟用。
//
// 這裡**沒有掃描線**，而且不該加回來。掃描線是 CRT 的產物，不是底片的，
// 真正的電影感堆疊（Unity / Unreal 的參考實作）也不含它。更實際的問題是：
// 任何以正規化 uv 表示的固定頻率條紋，週期都會隨視窗尺寸與 DPI 改變，
// 一旦接近像素格點就產生低頻拍頻 —— 畫面上看到的不是細緻掃描線，
// 而是大塊的斑馬紋。曾實測 sin(uv.y * 880.0) 在 760 px 高的視窗下
// 每 5.4 px 一條，斑馬紋清晰可見。
//
// 顆粒用的是雜湊噪點，沒有週期性，因此不會有同樣的問題。
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
    float pulse;       // 低頻能量 0..1，讓暗角隨鼓點收縮
    vec4  tint;        // 主色，給暗角一點色偏而非死黑
};

// 以「整數像素座標」做位元雜湊，而不是對正規化 uv 乘一個大常數再取小數。
//
// 為什麼不用常見的 fract(sin(dot(...))) 或 fract(p * 443.897)：
//
// 1. **浮點精度會崩潰。** 那類雜湊把時間直接加進座標，時間單調遞增，
//    乘上大常數後很快突破 float32 的 24-bit 尾數能表示的範圍。
//    一旦有效位不足，fract() 就從亂數退化成低頻結構 ——
//    畫面上會出現大塊、而且隨時間往下捲動的斑馬紋。實測跑幾分鐘就發生。
// 2. **顆粒大小會隨視窗尺寸改變。** uv 是正規化的，uv * 1024 在
//    1180 px 寬的視窗上，相鄰像素只差 0.87，雜湊值彼此相關，
//    畫出來是糊成一團的斑塊而不是細顆粒。
//
// 整數雜湊（PCG 風格的位元攪拌）兩個問題都沒有：輸入是像素索引與有界的
// 幀計數，永遠是精確的整數，而且顆粒恆為 1 像素。
// 關鍵在兩點：**乘數要小**，而且**先 fract 再運算**。
// 輸入是像素座標（≤ 幾千）與有界的幀計數（0..1023），乘上 0.1031 之後
// 最大也才數百，float32 綽綽有餘；先取小數又把後續運算全部壓回 [0,1)。
// 舊寫法乘的是 443.897 且時間無上限，兩個條件都違反，才會退化成捲動條紋。
//
// 不用整數位元雜湊是因為 GLSL 100es / 120 這兩個相容性目標沒有 uint，
// 而我們希望著色器在沒有 D3D11 的舊機器上也能跑。
float hash13(vec3 seed) {
    seed = fract(seed * 0.1031);
    seed += dot(seed, seed.zyx + 31.32);
    return fract((seed.x + seed.y) * seed.z);
}

float pixelNoise(vec2 pixel, float frame) {
    return hash13(vec3(pixel, frame));
}

void main() {
    vec2 uv = qt_TexCoord0;

    // 暗角：橢圓形衰減，寬螢幕下上下邊比左右先暗，比正圓自然
    vec2 centered = uv - 0.5;
    float dist = length(centered * vec2(1.0, 0.94));
    float inner = 0.34 - pulse * 0.05;   // 鼓點時暗角往內收，畫面像被撞了一下
    float vig = smoothstep(inner, 0.88, dist) * vignette;

    // 底片顆粒：每幀換一次種子，靜態噪點看起來像髒掉的螢幕而不是底片。
    // time 由 QML 端維持在 0..1024 的有界範圍內循環，取整數後直接當幀計數。
    float n = pixelNoise(floor(gl_FragCoord.xy), floor(time)) - 0.5;
    float grainAlpha = abs(n) * grain;

    float alpha = clamp(vig + grainAlpha, 0.0, 1.0);
    if (alpha <= 0.0) {
        fragColor = vec4(0.0);
        return;
    }

    // 暗角帶一點主色色偏；顆粒是純黑白的亮暗點
    vec3 vignetteColour = mix(vec3(0.0), tint.rgb, 0.22) * 0.35;
    vec3 grainColour = vec3(step(0.0, n));

    vec3 colour = (vignetteColour * vig + grainColour * grainAlpha) / max(alpha, 1e-4);

    fragColor = vec4(colour * alpha, alpha) * qt_Opacity;
}
