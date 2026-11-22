#!/usr/bin/env python3
"""Install Contitext instructions and stdio adapters without changing unrelated settings."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib

from agent_jsonc import InstallError, parse_jsonc, member, insert_object_member

TARGETS = ('codex', 'claude', 'zed', 'hermes', 'openclaw', 'copilot', 'cursor', 'opencode', 'gemini')
BEGIN = '<!-- BEGIN CONTITEXT MANAGED BLOCK -->'
END = '<!-- END CONTITEXT MANAGED BLOCK -->'


def markdown(existing, protocol, target, legacy_markers):
    for label in legacy_markers:
        existing=re.sub(r'^# '+re.escape(label)+r'\s*$', '# Contitext', existing, flags=re.M|re.I)
        before=f'<!-- BEGIN {label} MANAGED BLOCK -->'
        after=f'<!-- END {label} MANAGED BLOCK -->'
        if before in existing or after in existing:
            if existing.count(before)!=1 or existing.count(after)!=1 or BEGIN in existing:
                raise InstallError('ambiguous legacy instruction blocks')
            existing=existing.replace(before,BEGIN).replace(after,END)
    block=f'{BEGIN}\n## Contitext adapter ({target})\n\nUse the `contitext` MCP server. Reload MCP or start a new agent session after installation.\n\n{protocol.rstrip()}\n{END}'
    if existing.count(BEGIN)!=existing.count(END) or existing.count(BEGIN)>1:
        raise InstallError('ambiguous Contitext instruction blocks')
    if BEGIN in existing:
        return re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END),lambda _:block,existing,flags=re.S).rstrip()+'\n'
    return (existing.rstrip()+'\n\n' if existing.strip() else '')+block+'\n'


def migrated_entry(servers, wrapper, legacy, style='standard'):
    matches=[key for key in ['contitext',*legacy] if key in servers]
    if len(matches)>1:
        raise InstallError('both old and new server entries exist; resolve the duplicate before installing')
    previous=servers[matches[0]] if matches else {}
    if not isinstance(previous,dict):raise InstallError('server configuration must be an object')
    previous=dict(previous)
    managed_launchers = {str(wrapper), str(wrapper.parent/'contitext-mcp-client')}
    previous_command=previous.get('command')
    if style=='opencode' and isinstance(previous_command,list) and len(previous_command)==1:
        previous_command=previous_command[0]
    if matches==['contitext'] and (not isinstance(previous_command,str) or previous_command not in managed_launchers):
        raise InstallError('existing Contitext entry uses another launcher; preserve it or migrate explicitly')
    for key in ['command','args','env','environment','env_vars','url','headers','bearer_token_env_var','cwd','type','transport']:
        previous.pop(key,None)
    original_tools={'project_bind','project_current','context_get','context_search','context_record','context_handoff'}
    tool_filter=previous.get('toolFilter')
    if isinstance(tool_filter,dict) and isinstance(tool_filter.get('include'),list) and set(tool_filter['include'])==original_tools:
        previous['toolFilter']={**tool_filter,'include':[*tool_filter['include'],'project_list','project_create']}
    if isinstance(previous.get('enabled_tools'),list) and set(previous['enabled_tools'])==original_tools:
        previous['enabled_tools']=[*previous['enabled_tools'],'project_list','project_create']
    if style=='opencode':previous.update(type='local',command=[str(wrapper)])
    else:previous.update(command=str(wrapper),args=[])
    return previous,matches[0] if matches else None


def node_value(text,node):
    if node.kind=='object':return {key:node_value(text,value) for key,value,_ in node.members}
    if node.kind=='array':return [node_value(text,child) for child in node.value]
    return node.value


def json_config(text, path, wrapper, legacy, defaults=None, style='standard'):
    text=text if text.strip() else '{}\n'
    root,_=parse_jsonc(text);node=root
    for index,key in enumerate(path):
        child=member(node,key)
        if child is None:
            entry,_=migrated_entry({},wrapper,legacy,style)
            for k,v in (defaults or {}).items():entry.setdefault(k,v)
            value={'contitext':entry}
            for part in reversed(path[index+1:]):value={part:value}
            result=insert_object_member(text,node,json.dumps(key)+': '+json.dumps(value,indent=2))
            parse_jsonc(result);return result.rstrip()+'\n'
        if child.kind!='object':raise InstallError('MCP configuration section must be an object')
        node=child
    servers={key:node_value(text,value) for key,value,_ in node.members if key in ['contitext',*legacy]}
    entry,old=migrated_entry(servers,wrapper,legacy,style)
    for k,v in (defaults or {}).items():entry.setdefault(k,v)
    if old=='contitext' and servers[old]==entry:return text
    rendered='"contitext": '+json.dumps(entry,indent=2)
    if old:
        value=member(node,old)
        key_start=next(start for key,_,start in node.members if key==old)
        result=text[:key_start]+rendered+text[value.end:]
    else:result=insert_object_member(text,node,rendered)
    parse_jsonc(result)
    return result.rstrip()+'\n'


def opencode_config(text,wrapper,legacy,major):
    document=node_value(text,parse_jsonc(text)[0]) if text.strip() else {}
    mcp=document.get('mcp',{})
    if not isinstance(mcp,dict):raise InstallError('OpenCode mcp configuration must be an object')
    if major==1 and 'servers' in mcp:
        raise InstallError('OpenCode V2 configuration found; select --opencode-major 2')
    if major==2:
        reserved={'servers','timeout','protocol','disabled','codemode','pool'}
        if set(mcp)-reserved:
            raise InstallError('OpenCode V1 or unknown MCP layout; use --opencode-major 1 or migrate it explicitly')
    return json_config(text,['mcp'] if major==1 else ['mcp','servers'],wrapper,legacy,
                       {'enabled':True} if major==1 else None,style='opencode')


def toml_value(value):
    if isinstance(value,dict):return '{ '+', '.join(json.dumps(str(k))+' = '+toml_value(v) for k,v in value.items())+' }'
    if isinstance(value,list):return '['+', '.join(toml_value(v) for v in value)+']'
    if isinstance(value,(str,int,float,bool)):return json.dumps(value,ensure_ascii=False)
    raise InstallError('unsupported value in MCP TOML configuration')


def codex_config(text,wrapper,legacy):
    document=tomllib.loads(text)
    servers=document.get('mcp_servers',{})
    entry,old=migrated_entry(servers,wrapper,legacy)
    names=set([old] if old else [])
    # Inspect headers with the standard parser; retain every unrelated table byte for byte.
    lines=text.splitlines(keepends=True);out=[];skip=False;removed=False
    for line in lines:
        if line.lstrip().startswith('['):
            try:
                header=tomllib.loads(line+'\n__contitext_probe__ = true\n')
                section=header.get('mcp_servers',{})
                skip=any(name in section for name in names)
                removed=removed or skip
            except tomllib.TOMLDecodeError:
                if skip:raise InstallError('unsupported multiline MCP table header')
                skip=False
        if not skip:out.append(line)
    if old and not removed:raise InstallError('MCP TOML entry is not a standalone table')
    result=''.join(out).rstrip()+'\n\n[mcp_servers.contitext]\n'+'\n'.join(json.dumps(k)+' = '+toml_value(v) for k,v in entry.items())+'\n'
    parsed=tomllib.loads(result)
    before={k:v for k,v in document.items() if k!='mcp_servers'}
    after={k:v for k,v in parsed.items() if k!='mcp_servers'}
    if before!=after:raise InstallError('unrelated TOML settings changed; refusing to install')
    for key,value in servers.items():
        if key not in names and parsed['mcp_servers'].get(key)!=value:raise InstallError('unrelated MCP entry changed')
    return result.lstrip('\n')


def yaml_document(text,interpreter):
    helper='import json,sys,yaml; print(json.dumps(yaml.safe_load(sys.stdin.read()) or {}))'
    result=subprocess.run([interpreter,'-c',helper],input=text,text=True,capture_output=True,timeout=15)
    if result.returncode:raise InstallError('cannot parse Hermes YAML; provide --yaml-python pointing to its Python environment with PyYAML')
    return json.loads(result.stdout)


def hermes_config(text,wrapper,legacy,interpreter):
    document=yaml_document(text,interpreter)
    servers=document.get('mcp_servers',{}) or {}
    entry,old=migrated_entry(servers,wrapper,legacy)
    updated=dict(servers)
    if old:updated.pop(old)
    entry.setdefault('connect_timeout',60)
    updated['contitext']=entry
    if old=='contitext' and servers==updated:return text
    lines=text.splitlines(keepends=True)
    indices=[i for i,line in enumerate(lines) if re.match(r'^mcp_servers\s*:',line)]
    if len(indices)>1:raise InstallError('duplicate Hermes mcp_servers mappings')
    block='mcp_servers: '+json.dumps(updated,ensure_ascii=False)+'\n'
    if indices:
        start=indices[0];end=start+1
        while end<len(lines) and (not lines[end].strip() or lines[end][0].isspace() or lines[end].lstrip().startswith('#')):end+=1
        result=''.join(lines[:start])+block+''.join(lines[end:])
    else:result=text.rstrip()+'\n\n'+block
    parsed=yaml_document(result,interpreter)
    if {k:v for k,v in parsed.items() if k!='mcp_servers'}!={k:v for k,v in document.items() if k!='mcp_servers'}:
        raise InstallError('unrelated Hermes settings changed')
    return result


def safe_path(path,home):
    try:relative=path.relative_to(home)
    except ValueError:raise InstallError('installation destination escapes home')
    current=home
    for part in ('.',*relative.parts):
        current=current/part
        if current.is_symlink():raise InstallError('refusing to modify a symlink destination')
    if path.exists() and not path.is_file():raise InstallError('destination is not a regular file')


def atomic(path,data,mode):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True,help='JSON stdio command/args, or client-config output. No embedded environment secrets.')
    parser.add_argument('--home',type=Path,default=Path.home())
    parser.add_argument('--target',choices=TARGETS,action='append',required=True)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--replace-server',action='append',default=[])
    parser.add_argument('--replace-marker',action='append',default=[])
    parser.add_argument('--replace-skill',action='append',default=[])
    parser.add_argument('--yaml-python',help='Hermes Python interpreter with PyYAML; defaults to its installed venv when available.')
    parser.add_argument('--opencode-major',type=int,choices=[1,2],default=2,help='Explicit OpenCode configuration generation; defaults to current V2. Existing other layouts are never migrated implicitly.')
    args=parser.parse_args(argv)
    home=args.home.expanduser().absolute()
    originals={}
    def read(path):
        safe_path(path,home)
        value=path.read_bytes() if path.exists() else None
        if path in originals and originals[path]!=value:raise InstallError('configuration changed during planning')
        originals[path]=value
        return value.decode() if value is not None else ''
    try:
        config=json.loads(args.config.read_text())
        if 'mcpServers' in config:config=config['mcpServers']['contitext']
        if set(config)-{'command','args'} or not isinstance(config.get('command'),str) or not config['command']:
            raise InstallError('provide only a nonempty stdio command and string arguments; keep credentials in protected server configuration')
        if not isinstance(config.get('args',[]),list) or any(not isinstance(x,str) for x in config.get('args',[])):
            raise InstallError('stdio arguments must be strings')
        for name in args.replace_server+args.replace_skill:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',name):raise InstallError('invalid legacy name')
        protocol=(Path(__file__).resolve().parent.parent/'integrations/PROJECT-CONTEXT-PROTOCOL.md').read_text()
        wrappers={target:home/('.local/bin/contitext-mcp-'+target) for target in dict.fromkeys(args.target)}
        plan={}
        for wrapper in wrappers.values():
            read(wrapper)
            plan[wrapper]=('#!/bin/sh\nset -eu\nexec '+shlex.join([config['command'],*config.get('args',[])])+'\n').encode()
        instruction_paths={'codex':home/'.codex/AGENTS.md','claude':home/'.claude/CLAUDE.md','zed':home/'.config/zed/AGENTS.md','hermes':home/'.hermes/skills/contitext/SKILL.md','openclaw':home/'.openclaw/skills/contitext/SKILL.md',
                           'copilot':home/'.copilot/copilot-instructions.md','cursor':home/'.cursor/skills/contitext/SKILL.md','opencode':home/'.config/opencode/AGENTS.md','gemini':home/'.gemini/GEMINI.md'}
        config_paths={'codex':home/'.codex/config.toml','claude':home/'.claude.json','zed':home/'.config/zed/settings.json','hermes':home/'.hermes/config.yaml','openclaw':home/'.openclaw/openclaw.json',
                      'copilot':home/'.copilot/mcp-config.json','cursor':home/'.cursor/mcp.json','opencode':home/'.config/opencode/opencode.json','gemini':home/'.gemini/settings.json'}
        if 'opencode' in args.target:
            plain=config_paths['opencode'];commented=plain.with_suffix('.jsonc')
            safe_path(plain,home);safe_path(commented,home)
            if plain.exists() and commented.exists():raise InstallError('both OpenCode JSON and JSONC configurations exist; select one before installing')
            if commented.exists():config_paths['opencode']=commented
        yaml_python=args.yaml_python
        if not yaml_python:
            candidate=home/'.hermes/hermes-agent/venv/bin/python'
            yaml_python=str(candidate) if candidate.is_file() else sys.executable
        for target in dict.fromkeys(args.target):
            wrapper=wrappers[target]
            path=instruction_paths[target];safe_path(path,home)
            existing=read(path)
            if target in ('hermes','openclaw','cursor'):
                for old in args.replace_skill:
                    legacy=path.parent.parent/old/'SKILL.md';safe_path(legacy,home)
                    if legacy.exists():
                        raw=read(legacy)
                        if not any(f'<!-- BEGIN {label} MANAGED BLOCK -->' in raw for label in args.replace_marker):
                            raise InstallError('legacy skill is not marked as managed; refusing to remove it')
                        if existing:raise InstallError('old and new skill files both exist; resolve before installing')
                        raw=re.sub(r'\A---\n.*?\n---\n','',raw,flags=re.S)
                        existing=raw;plan[legacy]=None
                if existing.startswith('---\n'):
                    existing=re.sub(r'\A---\n.*?\n---\n','',existing,count=1,flags=re.S).lstrip('\n')
                header='---\nname: contitext\ndescription: "Use Contitext MCP for explicit project selection, context, checkpoints, and handoffs."\n---\n\n'
                content=header+markdown(existing.lstrip("\n"),protocol,target,args.replace_marker)
            else:content=markdown(existing,protocol,target,args.replace_marker)
            plan[path]=content.encode()
            path=config_paths[target];safe_path(path,home)
            original=read(path)
            if target=='codex':updated=codex_config(original,wrapper,args.replace_server)
            elif target=='hermes':updated=hermes_config(original,wrapper,args.replace_server,yaml_python)
            elif target=='opencode':updated=opencode_config(original,wrapper,args.replace_server,args.opencode_major)
            else:
                parts={'claude':['mcpServers'],'zed':['context_servers'],'openclaw':['mcp','servers'],
                       'copilot':['mcpServers'],'cursor':['mcpServers'],'gemini':['mcpServers']}[target]
                defaults={'connectionTimeoutMs':60000,'requestTimeoutMs':120000} if target=='openclaw' else None
                if target=='copilot':defaults={'type':'stdio','tools':['*']}
                updated=json_config(original,parts,wrapper,args.replace_server,defaults)
                for label in args.replace_marker:
                    for boundary in ('BEGIN','END'):
                        updated=updated.replace('// '+boundary+' '+label+' MANAGED MCP', '// '+boundary+' CONTITEXT MANAGED MCP')
            plan[path]=updated.encode()
        for path in plan:
            safe_path(path,home)
        changes={p:data for p,data in plan.items() if originals[p]!=data}
        backup=home/'.local/state/contitext/adapter-backups'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        if not args.dry_run and changes:
            safe_path(backup/'manifest.json',home)
            backup.mkdir(parents=True,mode=0o700)
            for path,data in changes.items():
                if (path.read_bytes() if path.exists() else None)!=originals[path]:raise InstallError('configuration changed during planning; retry installation')
                if originals[path] is not None:atomic(backup/path.relative_to(home),originals[path],0o600)
            for path,data in changes.items():
                if (path.read_bytes() if path.exists() else None)!=originals[path]:raise InstallError('configuration changed during installation; backups retained')
                if data is None:path.unlink()
                else:atomic(path,data,0o755 if path in wrappers.values() else (stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600))
        print(json.dumps({'status':'dry-run' if args.dry_run else 'installed','targets':list(dict.fromkeys(args.target)),'changed':[str(p) for p in changes],'backup':str(backup) if changes and not args.dry_run else None,'launchers':{k:str(v) for k,v in wrappers.items()},'reload_required':bool(changes)},indent=2))
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        # Configuration can contain secrets. Do not print parser payloads or child stderr.
        message=str(exc) if isinstance(exc,InstallError) else 'invalid configuration or inaccessible file; no credentials printed'
        parser.error(message)

if __name__=='__main__':main()
