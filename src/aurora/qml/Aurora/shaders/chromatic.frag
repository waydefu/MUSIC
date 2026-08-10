#version 440

// 色散（chromatic aberration）：模擬鏡頭無法把三原色聚焦到同一點。
//
// 位移量隨距離畫面中心的半徑增加 —— 真實鏡頭就是這樣，中央銳利、
// 邊緣散開。強度刻意壓得很低（預設不到 2 px），Unity 與 Unreal 的
// 官方指引都強調這個效果一過量就變成廉價濾鏡。
//
// 鼓點時瞬間拉高再衰減，讓畫面像被聲音撞了一下。

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float amount;       // 位移強度，以畫面寬度的比例計
};

layout(binding = 1) uniform sampler2D source;

void main() {
    vec2 uv = qt_TexCoord0;
    vec2 centered = uv - 0.5;

    // 半徑平方讓中央幾乎不受影響，邊緣才明顯
    float falloff = dot(centered, centered) * 4.0;
    vec2 offset = centered * amount * falloff;

    // 紅藍往相反方向偏，綠留在原位 —— 這是最典型的橫向色差樣貌
    float r = texture(source, uv + offset).r;
    vec4  g = texture(source, uv);
    float b = texture(source, uv - offset).b;

    fragColor = vec4(r, g.g, b, g.a) * qt_Opacity;
}
