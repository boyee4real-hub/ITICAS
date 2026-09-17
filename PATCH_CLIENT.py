from pathlib import Path
ROOT=Path(r"C:\ITICAS_BUILD\ITICAS_v0.26.3_WINDOWS_DISTRIBUTION_KIT\source\ITICAS_v0.26.3_DISTRIBUTION_SOURCE")
APP=ROOT/"backend"/"app"
main=(APP/"main.py").read_text(encoding="utf-8")
if "from .central_access import" not in main:
    anchor="from .security import ("
    i=main.find(anchor)
    if i<0: raise SystemExit("[FAIL] main.py security import anchor not found")
    main=main[:i]+"from .central_access import gateway_configured, submit_access_request, central_login, sync_central_user\n"+main[i:]
start=main.find('@app.get("/login", response_class=HTMLResponse)')
end=main.find('@app.post("/logout")',start)
if start<0 or end<0: raise SystemExit("[FAIL] login/register route block not found")
block='''@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_user_optional(request): return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"login.html", context(request))

@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    check_login_rate_limit(request)
    if gateway_configured():
        try: profile=await central_login(username,password)
        except RuntimeError:
            return templates.TemplateResponse(request,"login.html",context(request,error="ITICAS central access service is temporarily unavailable. Please try again shortly."),status_code=503)
        if not profile:
            return templates.TemplateResponse(request,"login.html",context(request,error="Invalid credentials or account is not yet approved."),status_code=401)
        user=sync_central_user(profile,password)
    else:
        user=authenticate(username,password)
        if not user:
            return templates.TemplateResponse(request,"login.html",context(request,error="Invalid credentials, account pending, disabled, or temporarily locked."),status_code=401)
    clear_login_rate_limit(request)
    raw=create_session(user,request)
    response=RedirectResponse("/",303)
    response.set_cookie(settings.security_cookie_name,raw,httponly=True,secure=settings.security_cookie_secure,samesite="strict",max_age=settings.security_session_hours*3600,path="/")
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request,"register.html", context(request))

@app.post("/register")
async def register_submit(request:Request,full_name:str=Form(...),username:str=Form(...),email:str=Form(...),organisation:str=Form(""),phone:str=Form(""),intended_use:str=Form(...),password:str=Form(...),confirm_password:str=Form(...)):
    if password!=confirm_password:
        return templates.TemplateResponse(request,"register.html",context(request,error="Passwords do not match."),status_code=400)
    if not gateway_configured():
        return templates.TemplateResponse(request,"register.html",context(request,error="Central ITICAS access service is not yet activated on this build."),status_code=503)
    try:
        result=await submit_access_request({"full_name":full_name.strip(),"username":username.strip(),"email":email.strip().lower(),"organisation":organisation.strip(),"phone":phone.strip(),"intended_use":intended_use.strip(),"password":password})
    except RuntimeError as exc:
        return templates.TemplateResponse(request,"register.html",context(request,error=str(exc)),status_code=502)
    return templates.TemplateResponse(request,"register.html",context(request,success=result.get("message") or "Access request submitted."))

'''
main=main[:start]+block+main[end:]
(APP/"main.py").write_text(main,encoding="utf-8")
config=(APP/"config.py").read_text(encoding="utf-8")
if "access_gateway_url:" not in config:
    marker="    security_password_min_length: int = 12\n"
    addition="    security_password_min_length: int = 12\n\n    access_gateway_url: str | None = None\n    access_gateway_timeout_seconds: float = 20.0\n"
    if marker not in config: raise SystemExit("[FAIL] config marker not found")
    config=config.replace(marker,addition,1)
(APP/"config.py").write_text(config,encoding="utf-8")
print("[PASS] Client login/registration patched for central gateway")
