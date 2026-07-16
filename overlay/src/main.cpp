#include <windows.h>
#include <string>

// Global variables
HWND g_hwnd = NULL;
const wchar_t* g_text = L"Learning Platform Active";

// Window procedure
LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            
            RECT rect;
            GetClientRect(hwnd, &rect);
            
            // Fill with transparent color (will be keyed out)
            HBRUSH brush = CreateSolidBrush(RGB(255, 0, 255)); // Magenta - will be transparent
            FillRect(hdc, &rect, brush);
            DeleteObject(brush);
            
            // Draw text in white
            SetTextColor(hdc, RGB(255, 255, 255));
            SetBkMode(hdc, TRANSPARENT);
            
            HFONT font = CreateFontW(48, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                     DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                     DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Arial");
            SelectObject(hdc, font);
            
            DrawTextW(hdc, g_text, -1, &rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
            
            DeleteObject(font);
            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_ERASEBKGND:
            return 1; // Prevent background erasing
        case WM_CLOSE:
            DestroyWindow(hwnd);
            return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR cmd, int show) {
    // Register window class
    WNDCLASSW wc = {};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.hbrBackground = CreateSolidBrush(RGB(255, 0, 255)); // Magenta background
    wc.lpszClassName = L"OverlayClass";
    
    if (!RegisterClassW(&wc)) return 1;
    
    // Create window with layered style
    g_hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        L"OverlayClass",
        L"",
        WS_POPUP,
        100, 100, 600, 200,
        NULL, NULL, hInst, NULL
    );
    
    if (!g_hwnd) return 1;
    
    // Make magenta transparent (color keying)
    SetLayeredWindowAttributes(g_hwnd, RGB(255, 0, 255), 0, LWA_COLORKEY);
    
    // Show the window
    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);
    
    // Message loop
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}