"""Bounded source evidence for native integration points; this is not a compiler.

Only explicit, typed source paths are recognized. Unknown or ambiguous syntax
fails for review, never passes by name.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re

from .behavior import _target_tokens, _target_pairs, _selected_handler_bodies
from .core import MigrationError, read_json, safe_child

SKIP = {'oh_modules','node_modules','build','.git','.hmigbot-ios','.agents','.codex','.preview','.cxx'}
TEST_PARTS = {'test','tests','ohosTest','__tests__'}
IDENT = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')


@dataclass
class Member:
    name: str
    index: int
    kind: str
    static: bool
    type_tokens: list
    body: tuple | None = None


@dataclass
class Definition:
    source: object
    name: str
    start: int
    end: int
    members: dict
    kind: str = 'class'
    exported: bool = False


@dataclass
class Binding:
    name: str
    index: int
    kind: str
    exported: bool
    type_tokens: list
    initializer: int | None = None


class Source:
    def __init__(self, path, project):
        self.path = path
        self.relative = path.relative_to(project).as_posix()
        self.text = path.read_text(encoding='utf-8-sig')
        self.tokens = _target_tokens(self.text)
        self.pairs = _target_pairs(self.tokens)
        self.values = [t.value for t in self.tokens]
        self.imports = self._imports()
        self.reexports = self._imports('export')
        self.bindings = self._bindings()
        self.definitions = []
        for i, token in enumerate(self.tokens[:-2]):
            if token.value not in {'class','struct','interface'} or not IDENT.fullmatch(self.values[i+1]):
                continue
            opening = i + 2
            while opening < len(self.tokens) and self.values[opening] not in {'{',';'}:
                opening += 1
            if opening not in self.pairs:
                continue
            end = self.pairs[opening]
            exported=i>0 and self.values[i-1]=='export' or i>1 and self.values[i-2:i]==['export','default']
            self.definitions.append(Definition(self,self.values[i+1],opening,end,self._members(opening,end),token.value,exported))

    def _imports(self, keyword='import'):
        active = {t.line for t in self.tokens if t.value == keyword and not t.literal}
        imports = {}
        pattern = r"(?m)^"+keyword+r"[ \t]+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(pattern,self.text):
            if self.text[:match.start()].count('\n')+1 not in active:
                continue
            raw = match[2]
            if not raw.startswith('.'):
                continue
            target = (self.path.parent / raw).with_suffix('.ets').resolve()
            for part in match[1].split(','):
                names = re.fullmatch(r'\s*([\w$]+)(?:\s+as\s+([\w$]+))?\s*',part)
                if names:
                    local = names[2] or names[1]
                    imports.setdefault(local,[]).append((target,names[1]))
        return imports

    def _bindings(self):
        result={}; cursor=0
        while cursor<len(self.tokens)-1:
            if self.values[cursor] in {'const','let','var'} and IDENT.fullmatch(self.values[cursor+1]):
                name=self.values[cursor+1]; after=cursor+2; types=[]
                if after<len(self.tokens) and self.values[after]==':':
                    start=after+1;after=start
                    while after<len(self.tokens) and self.values[after] not in {'=',';'} and self.tokens[after].line==self.tokens[start].line:
                        after+=1
                    types=self.tokens[start:after]
                initializer=after+1 if after<len(self.tokens) and self.values[after]=='=' else None
                result.setdefault(name,[]).append(Binding(name,cursor+1,self.values[cursor],
                    cursor>0 and self.values[cursor-1]=='export',types,initializer))
            cursor=self.pairs[cursor]+1 if cursor in self.pairs else cursor+1
        return result

    def _members(self, opening, end):
        result, i, declaration = {}, opening+1, opening+1
        while i < end:
            value = self.values[i]
            if IDENT.fullmatch(value) and i+1 < end:
                following = self.values[i+1]
                if following == '(' and i+1 in self.pairs:
                    bodies = _selected_handler_bodies(self.tokens,i,self.pairs)
                    bodies = [b for b in bodies if b < end]
                    if bodies:
                        body = bodies[0]
                        after = self.pairs[i+1]+1
                        types = self.tokens[after+1:body] if self.values[after] == ':' else []
                        kind = 'getter' if i > opening and self.values[i-1] == 'get' else 'method'
                        previous = self.values[declaration:i]
                        member = Member(value,i,kind,'static' in previous,types,(body,self.pairs[body]))
                        result.setdefault(value,[]).append(member)
                        i = self.pairs[body]+1
                        declaration = i
                        continue
                elif following == ':' or following=='?' and i+2<end and self.values[i+2]==':':
                    type_start=i+3 if following=='?' else i+2
                    after=type_start
                    while after < end and self.values[after] not in {'=',';','}'} and self.tokens[after].line == self.tokens[i].line:
                        after += 1
                    types=self.tokens[type_start:after]
                    result.setdefault(value,[]).append(Member(value,i,'field','static' in self.values[declaration:i],types))
            if i in self.pairs:
                i=self.pairs[i]+1
                declaration=i
            else:
                if value == ';': declaration=i+1
                i+=1
        return result


def _one(values):
    return values[0] if len(values) == 1 else None


def _event(definition, member, role):
    return {'role':role,'file':definition.source.relative,'line':definition.source.tokens[member.index].line,
            'class':definition.name,'member':member.name}


def product_source_roots(project):
    """Use declared HarmonyOS modules, never a project-wide ETS search.

    The bundled core reader accepts JSON-compatible JSON5 configuration. A
    configuration it cannot parse fails explicitly; it cannot widen the scan
    into historical evidence, test modules or arbitrary project directories.
    """
    profile=read_json(safe_child(project,'build-profile.json5'))
    modules=profile.get('modules') if isinstance(profile,dict) else None
    if not isinstance(modules,list) or not modules:
        raise MigrationError('Native source indexing requires declared build-profile modules')
    roots=[]; names=set(); paths=set()
    for declaration in modules:
        if not isinstance(declaration,dict):
            raise MigrationError('Malformed build-profile module declaration')
        name=declaration.get('name'); relative=declaration.get('srcPath')
        if not isinstance(name,str) or not name or name in names or not isinstance(relative,str) or not relative:
            raise MigrationError('Module needs a unique name and explicit srcPath')
        names.add(name)
        relative=relative[2:] if relative.startswith('./') else relative
        module=project if relative in {'','.'} else safe_child(project,relative)
        # safe_child's IO subclass adds Windows long-path prefixes when passed
        # to os.walk; keep path identities in their normal project namespace.
        module=Path(str(module))
        if module in paths or any(part in SKIP or part in TEST_PARTS or part.startswith('.')
                                  for part in module.relative_to(project).parts):
            raise MigrationError('Duplicate or non-product module source path')
        if module.relative_to(project).parts[:1] in [('spec',),('work',)]:
            raise MigrationError('Module source path points at control or historical evidence')
        paths.add(module)
        module_config=(module/'src/main/module.json5').resolve()
        if not module_config.is_relative_to(project):
            raise MigrationError('Configured module identity escapes project')
        config=read_json(module_config)
        identity=config.get('module') if isinstance(config,dict) else None
        if not isinstance(identity,dict) or identity.get('name')!=name or not identity.get('type'):
            raise MigrationError('Build-profile module differs from its main module identity: '+name)
        source=(module/'src/main/ets').resolve()
        if not source.is_relative_to(project):
            raise MigrationError('Configured product source escapes project: '+str(source))
        if source.is_dir(): roots.append(source)
    if not roots: raise MigrationError('No configured product ArkTS source root exists')
    return roots


class EvidenceIndex:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.sources = []
        self.source_roots=product_source_roots(self.project)
        for source_root in self.source_roots:
            for parent, directories, names in os.walk(source_root):
                directories[:] = sorted(d for d in directories if d not in SKIP|TEST_PARTS and not d.startswith('.'))
                for name in sorted(names):
                    path = Path(parent) / name
                    if path.suffix == '.ets':
                        resolved = path.resolve()
                        if not resolved.is_relative_to(source_root):
                            raise ValueError('Product source escapes configured source root: ' + str(path))
                        self.sources.append(Source(resolved,self.project))
        self.definitions = [d for s in self.sources for d in s.definitions]

    def definition(self, name, source=None):
        if source is None:
            return _one([d for d in self.definitions if d.name == name])
        local = [d for d in source.definitions if d.name == name]
        imports = source.imports.get(name,[])
        if local and imports: return None
        if local: return _one(local)
        binding = _one(imports)
        if binding is None: return None
        path, remote = binding
        return self._exported_definition(path,remote,set())

    def _exported_definition(self, path, name, seen):
        identity=(path,name)
        if identity in seen or len(seen)>=8: return None
        seen={*seen,identity}
        definitions=[d for d in self.definitions if d.name==name and d.source.path==path and d.exported]
        if definitions: return _one(definitions)
        source=next((source for source in self.sources if source.path==path),None)
        if source is None: return None
        forwarding=_one(source.reexports.get(name,[]))
        return self._exported_definition(*forwarding,seen) if forwarding else None

    def _binding(self, source, name):
        local=_one(source.bindings.get(name,[]))
        imported=_one(source.imports.get(name,[]))
        if local is not None and imported is not None: return None
        if local is not None: return source,local
        if imported is None: return None
        path,remote=imported
        provider=next((item for item in self.sources if item.path==path),None)
        if provider is None: return None
        binding=_one(provider.bindings.get(remote,[]))
        return (provider,binding) if binding and binding.exported else None

    def _binding_slot(self, source, name, slot):
        resolved=self._binding(source,name)
        if resolved is None: return None
        provider,binding=resolved
        values=[token.value for token in binding.type_tokens]
        if len(values)!=1: return None
        interface=self.definition(values[0],provider)
        if interface is None or interface.kind!='interface': return None
        field=_one(interface.members.get(slot,[]))
        if field is None: return None
        expected=self.member_type(interface,field)
        if expected is None: return None
        vals=provider.values; candidates=[]
        if binding.initializer is not None: candidates.append(binding.initializer)
        for index in range(len(vals)-2):
            if vals[index:index+2]==[binding.name,'='] and (index==0 or vals[index-1] not in {'.','const','let','var'}):
                candidates.append(index+2)
        # A local declaration or parameter with the shared export's name makes
        # producer binding ambiguous. No same-name inference is allowed.
        for index,token in enumerate(provider.tokens):
            if token.value!=binding.name or index==binding.index: continue
            if index and vals[index-1] in {'const','let','var'}: return None
            if index+1<len(vals) and vals[index+1]==':' and index and vals[index-1] in {'(',','}: return None
        producers=[]
        for opening in sorted(set(candidates)):
            if opening not in provider.pairs or vals[opening]!='{': return None
            entry=self._producer_entry(provider,opening)
            if entry is None: return None
            found=[]
            for start,end in self._segments_object(provider,opening):
                if vals[start:start+2]!=[slot,':']: continue
                if vals[start+2:start+3]!=['new'] or start+4>=end: return None
                constructor=self.definition(vals[start+3],provider)
                if constructor!=expected or vals[start+4]!='(' or provider.pairs.get(start+4)!=end-1: return None
                found.append({'role':'binding-producer','file':provider.relative,'line':provider.tokens[start].line,
                              'binding':binding.name,'slot':slot,'class':expected.name})
            if len(found)!=1: return None
            producers.extend([*found,*entry])
        if not producers: return None
        return expected,[{'role':'shared-binding','file':provider.relative,'line':provider.tokens[binding.index].line,
                          'binding':binding.name},_event(interface,field,'binding-interface'),*producers]

    def _producer_entry(self, provider, position):
        """A delayed producer must have an exact invocation from a product member.

        This is a bounded source chain, not a whole-program reachability claim.
        A declared but uncalled factory cannot initialize a shared export.
        """
        functions=[]; cursor=0; values=provider.values
        while cursor<len(values)-1:
            if values[cursor]=='function' and IDENT.fullmatch(values[cursor+1]):
                bodies=_selected_handler_bodies(provider.tokens,cursor+1,provider.pairs)
                functions.extend((cursor+1,body,provider.pairs[body]) for body in bodies)
            cursor=provider.pairs[cursor]+1 if cursor in provider.pairs else cursor+1
        enclosing=[item for item in functions if item[1]<position<item[2]]
        if not enclosing:
            # An initializer nested in any other block is unsupported.
            return [] if not any(values[start]=='{' and start<position<end
                                 for start,end in provider.pairs.items()) else None
        selected=_one(enclosing)
        if selected is None: return None
        declaration,begin,end=selected; name=values[declaration]
        if self._local_callable_contains(provider,begin,end,position): return None
        for consumer in self.sources:
            imported=_one(consumer.imports.get(name,[]))
            if consumer!=provider and imported!=(provider.path,name): continue
            if consumer!=provider and not (declaration>1 and values[declaration-2]=='export'): continue
            if consumer!=provider and consumer.bindings.get(name): continue
            for owner in consumer.definitions:
                for members in owner.members.values():
                    for member in members:
                        if not member.body: continue
                        left,right=member.body
                        if self._shadowed_parameter(consumer,name,left,right): continue
                        for index in range(left+1,right-1):
                            if consumer.values[index:index+2]!=[name,'(']: continue
                            if index and consumer.values[index-1] in {'.','function','new'}: continue
                            if self._local_callable_contains(consumer,left,right,index): continue
                            return [{'role':'producer-factory','file':provider.relative,
                                     'line':provider.tokens[declaration].line,'function':name},
                                    {'role':'producer-invocation','file':consumer.relative,
                                     'line':consumer.tokens[index].line,'class':owner.name,'member':member.name}]
        return None

    @staticmethod
    def _segments_object(source, opening):
        return EvidenceIndex._segments(source,opening)

    def top_binding_proof(self, relative, handler):
        provider=next((source for source in self.sources if source.relative==relative),None)
        if provider is None: return []
        binding=_one(provider.bindings.get(handler,[]))
        if binding is None or not binding.exported or binding.kind not in {'const','let'}: return []
        for consumer in self.sources:
            for index in range(len(consumer.values)-5):
                values=consumer.values
                if values[index:index+2]!=[handler,'.'] or values[index+3]!='.': continue
                if not any(member.body and member.body[0]<index<member.body[1]
                           and not self._local_callable_contains(consumer,*member.body,index)
                           for owner in consumer.definitions for members in owner.members.values() for member in members): continue
                if self._shadowed_parameter(consumer,handler,0,len(values)-1): continue
                resolved=self._binding(consumer,handler)
                if resolved is None or resolved[0]!=provider or resolved[1]!=binding: continue
                proof=self._binding_slot(consumer,handler,values[index+2])
                if proof is None: continue
                target,chain=proof
                member=_one(target.members.get(values[index+4],[]))
                if member is None or not self._consumed(target,member,index+5,source=consumer): continue
                return [*chain,{'role':'binding-consumer','file':consumer.relative,'line':consumer.tokens[index].line,
                                'member':values[index+4]},_event(target,member,'definition')]
        return []

    def member_type(self, definition, member):
        values=[t.value for t in member.type_tokens]
        # A single named class, optionally nullable. Arrays are only accepted
        # as provider collections below, never confused with a single value.
        named=[v for v in values if IDENT.fullmatch(v) and v not in {'undefined','null'}]
        if len(named)!=1 or any(v not in {named[0],'|','undefined','null','?'} for v in values):
            return None
        return self.definition(named[0],definition.source)

    def _provider(self, definition, member, expected):
        if member.kind != 'getter' or not member.body or self.member_type(definition,member) != expected:
            return None
        source=definition.source
        start,end=member.body
        vals=source.values
        # Bounded getters return an explicitly typed field or an element from
        # an explicitly typed collection. The declared return type alone is
        # insufficient evidence of a returned target object.
        returns=[]
        for i in range(start+1,end-3):
            if vals[i:i+3] != ['return','this','.']: continue
            field=_one(definition.members.get(vals[i+3],[]))
            if field is None or field.kind != 'field': continue
            types=[t.value for t in field.type_tokens]
            if self.member_type(definition,field) == expected:
                if vals[i+4] in {';','}'}:
                    returns.append(_event(definition,field,'provider-field'))
                continue
            named=[v for v in types if IDENT.fullmatch(v)]
            if len(named)!=1 or types not in [[named[0],'[',']']]: continue
            if self.definition(named[0],definition.source) != expected: continue
            after=i+4
            opening=after+2 if vals[after:after+3] == ['.','find','('] else after if vals[after]=='[' else None
            if opening in source.pairs:
                following=source.pairs[opening]+1
                if following==end or vals[following] in {';','}'}:
                    returns.append(_event(definition,field,'provider-collection'))
        return returns if returns else None

    def _self_provider(self, caller, provider, target):
        if (provider.kind!='method' or provider.static or not provider.body
                or self.member_type(caller,provider)!=target
                or self._segments(caller.source,provider.index+1)): return []
        source=caller.source; values=source.values; begin,end=provider.body
        returned=[]
        for index in range(begin+1,end):
            if values[index]!='return': continue
            if self._local_callable_contains(source,begin,end,index): continue
            if values[index+1:index+3]!=['this','.'] or values[index+4] not in {';','}'}: return []
            field=_one(caller.members.get(values[index+3],[]))
            if field is None or self.member_type(caller,field)!=target: return []
            returned.append(field)
        field=_one(returned)
        if field is None: return []
        for index in range(begin+1,end-6):
            if values[index:index+5]!=['this','.',field.name,'=','new']: continue
            if self._local_callable_contains(source,begin,end,index): continue
            if self.definition(values[index+5],source)!=target or values[index+6]!='(': return []
            closing=source.pairs.get(index+6)
            if closing is None or values[closing+1] not in {';','}'}: return []
            return [_event(caller,provider,'typed-self-provider'),_event(caller,field,'provider-field'),
                    {'role':'provider-initializer','file':source.relative,'line':source.tokens[index].line}]
        return []

    def _self_provider_calls(self, caller, handler, target, member):
        source=caller.source; values=source.values
        for begin,end,chain in self._handler_regions(caller,handler):
            for index in range(begin+1,end-4):
                if values[index:index+2]!=['this','.'] or values[index+3:index+5]!=['(',')']: continue
                if self._local_callable_contains(source,begin,end,index): continue
                provider=_one(caller.members.get(values[index+2],[]))
                if provider is None: continue
                proof=self._self_provider(caller,provider,target)
                if not proof: continue
                calls=[]
                if values[index+5:index+7]==['.',member.name]: calls.append(index+7)
                if index>=begin+4 and values[index-1]=='=' and values[index-3]=='const':
                    alias=values[index-2]
                    if IDENT.fullmatch(alias) and values[index+5]==';' and not self._shadowed_parameter(source,alias,index+5,end):
                        calls.extend(cursor+3 for cursor in range(index+6,end-3)
                                     if values[cursor:cursor+3]==[alias,'.',member.name]
                                     and not self._local_callable_contains(source,begin,end,cursor))
                for cursor in calls:
                    if self._consumed(caller,member,cursor):
                        return [{'role':'self-provider-call','file':source.relative,'line':source.tokens[cursor-2].line},
                                *chain,*proof,_event(target,member,'definition')]
        return []

    @staticmethod
    def _segments(source, opening):
        """Split direct arguments/parameters without splitting nested syntax."""
        end=source.pairs.get(opening)
        if end is None: return []
        result=[]; start=opening+1; cursor=start
        while cursor<end:
            if source.values[cursor]==',':
                result.append((start,cursor)); start=cursor+1
            cursor=source.pairs[cursor]+1 if cursor in source.pairs else cursor+1
        if start<end: result.append((start,end))
        return result

    def _parameter_calls(self, owner, method, target, member, parameter=None):
        if method.kind!='method' or not method.body or member.static: return []
        source=owner.source; values=source.values
        parameters=self._segments(source,method.index+1)
        for position,(start,end) in enumerate(parameters):
            if parameter is not None and position!=parameter: continue
            if start+2>=end or values[start+1]!=':': continue
            name=values[start]
            type_end=next((i for i in range(start+2,end) if values[i]=='='),end)
            typed=Member(name,start,'parameter',False,source.tokens[start+2:type_end])
            if self.member_type(owner,typed)!=target: continue
            begin,finish=method.body
            if self._shadowed_parameter(source,name,begin,finish): continue
            for i in range(begin+1,finish-2):
                if (values[i:i+3]==[name,'.',member.name] and self._consumed(owner,member,i+3)
                        and not self._local_callable_contains(source,begin,finish,i)):
                    return [_event(owner,method,'consumer-method'),_event(owner,typed,'typed-parameter'),
                            {'role':'parameter-call','file':source.relative,'line':source.tokens[i].line},
                            _event(target,member,'definition')]
        return []

    @staticmethod
    def _shadowed_parameter(source,name,begin,finish):
        """Reject rebinding or any nested binding of the same parameter name.

        This deliberately rejects ambiguous forms instead of attempting JS
        lexical resolution. Capturing an unchanged parameter in an arrow (the
        normal store.write callback) remains supported.
        """
        values=source.values
        for index in range(begin+1,finish):
            if values[index]!=name or values[index-1]=='.': continue
            following=values[index+1] if index+1<finish else ''
            if values[index-1] in {'const','let','var','class','function','catch'}:
                return True
            if following in {':','=','=>'}:
                return True
            # An untyped arrow/function argument can be a single identifier.
            for opening,closing in source.pairs.items():
                if values[opening]!='(' or not opening<index<closing: continue
                after=closing+1
                if after<len(values) and values[after]=='=>': return True
                if opening>0 and values[opening-1] in {'function','catch'}: return True
                if opening>1 and values[opening-2]=='function': return True
        return False

    def _handler_link(self, caller, handler, position, receiver, call_cursor):
        if handler.kind in {'method','getter'}:
            return any(begin<position<end and not self._local_callable_contains(caller.source,begin,end,position)
                       for begin,end,_ in self._handler_regions(caller,handler))
        if handler.kind!='field': return False
        if receiver==handler.name: return True
        source=caller.source
        if call_cursor>=len(source.values) or source.values[call_cursor]!='(': return False
        return any(source.values[start:end]==['this','.',handler.name]
                   for start,end in self._segments(source,call_cursor))

    @staticmethod
    def _local_callable_contains(source, begin, end, position):
        values=source.values
        for index in range(begin+1,min(position,end)):
            if values[index]=='function' and index+1<len(values):
                bodies=_selected_handler_bodies(source.tokens,index+1,source.pairs)
                if any(body<position<source.pairs[body] for body in bodies): return True
            if values[index] not in {'const','let','var'} or index+2>=end: continue
            cursor=index+2
            while cursor<end and values[cursor] not in {'=',';','{','}'}:
                cursor=source.pairs[cursor]+1 if cursor in source.pairs else cursor+1
            if cursor>=end or values[cursor]!='=': continue
            cursor+=1; arrow=None
            if cursor<end and values[cursor]=='function':
                arguments=cursor+1
                if arguments<end and IDENT.fullmatch(values[arguments]): arguments+=1
                if arguments in source.pairs and values[arguments]=='(':
                    body=source.pairs[arguments]+1
                    while body<end and values[body] not in {'{',';'}: body+=1
                    if body in source.pairs and body<position<source.pairs[body]: return True
            while cursor<end and values[cursor]!=';':
                if values[cursor]=='=>': arrow=cursor; break
                cursor=source.pairs[cursor]+1 if cursor in source.pairs else cursor+1
            if arrow is None or arrow>=position: continue
            body=arrow+1
            if body in source.pairs and values[body]=='{':
                if body<position<source.pairs[body]: return True
            elif position<end and not any(values[token]==';' for token in range(body,position)):
                return True
        return False

    def _handler_regions(self, caller, handler):
        if not handler.body: return []
        begin,end=handler.body
        regions=[(begin,end,[])]
        values=caller.source.values
        for index in range(begin+1,end-3):
            if values[index:index+2]!=['this','.'] or values[index+3]!='(': continue
            if self._local_callable_contains(caller.source,begin,end,index): continue
            helper=_one(caller.members.get(values[index+2],[]))
            if helper is None or helper is handler or helper.static or not helper.body: continue
            regions.append((*helper.body,[{'role':'handler-self-call','file':caller.source.relative,
                'line':caller.source.tokens[index].line,'from':handler.name,'to':helper.name},
                _event(caller,helper,'helper-definition')]))
        return regions

    def _handler_chain(self, caller, handler, position):
        for begin,end,chain in self._handler_regions(caller,handler):
            if begin<position<end: return chain
        return []

    @staticmethod
    def _scalar_type(member):
        values=[token.value for token in member.type_tokens]
        return frozenset(value for value in values if value!='|') if values and all(
            value in {'string','number','boolean','undefined','null','|'} for value in values) else None

    def _typed_scalar_write(self, caller, handler, target, member):
        source=caller.source; values=source.values
        if member.kind!='field': return []
        regions=self._handler_regions(caller,handler) if handler.body else [
            (*method.body,[]) for methods in caller.members.values() for method in methods if method.body]
        for begin,end,chain in regions:
            for index in range(begin+1,end-3):
                if self._local_callable_contains(source,begin,end,index): continue
                # Field/state <- exact typed receiver field, not an arbitrary
                # use of the target member somewhere in the component.
                if handler.kind=='field' and values[index:index+4]==['this','.',handler.name,'=']:
                    cursor=index+4
                    if values[cursor:cursor+2]!=['this','.']: continue
                    receiver=_one(caller.members.get(values[cursor+2],[]))
                    if receiver is None or self.member_type(caller,receiver)!=target: continue
                    if values[cursor+3:cursor+5]!=['.',member.name]: continue
                    following=cursor+5
                    if following>=len(values) or values[following] not in {';','}'}: continue
                    if self._scalar_type(handler)!=self._scalar_type(member) or self._scalar_type(member) is None: continue
                    return [{'role':'field-copy','file':source.relative,'line':source.tokens[index].line},
                            _event(caller,handler,'destination-field'),_event(caller,receiver,'typed-receiver'),
                            _event(target,member,'source-field')]
                # Planned method/getter -> this component's exact state field.
                if caller!=target or not handler.body or values[index:index+4]!=['this','.',member.name,'=']: continue
                cursor=index+4
                if cursor>=end: continue
                rhs=values[cursor]
                primitive=self._scalar_type(member)
                if primitive is None: continue
                allowed=False
                for start,finish in self._segments(source,handler.index+1):
                    if values[start]!=rhs or start+2>=finish or values[start+1]!=':': continue
                    parameter=Member(rhs,start,'parameter',False,source.tokens[start+2:finish])
                    if self._scalar_type(parameter)==primitive and not self._shadowed_parameter(source,rhs,begin,end): allowed=True
                if rhs in {'true','false'} and primitive==frozenset({'boolean'}): allowed=True
                if re.fullmatch(r'\d+',rhs) and primitive==frozenset({'number'}): allowed=True
                following=cursor+1
                if not allowed or following>=len(values) or values[following] not in {';','}'}: continue
                return [{'role':'self-field-write','file':source.relative,'line':source.tokens[index].line},
                        _event(caller,handler,'handler-definition'),_event(target,member,'destination-field'),*chain]
        return []

    def _forwarded_field(self, caller, field, target, member):
        """One explicit field-to-method-argument hop, then a typed parameter call."""
        source=caller.source; values=source.values
        for i in range(caller.start+1,caller.end-5):
            if values[i:i+2]!=['this','.']: continue
            provider_field=_one(caller.members.get(values[i+2],[]))
            if provider_field is None: continue
            provider=self.member_type(caller,provider_field)
            if provider is None or values[i+3]!='.' or values[i+5]!='(': continue
            callee=_one(provider.members.get(values[i+4],[]))
            if callee is None: continue
            for position,(start,end) in enumerate(self._segments(source,i+5)):
                if values[start:end]!=['this','.',field.name]: continue
                proof=self._parameter_calls(provider,callee,target,member,position)
                if proof:
                    return [{'role':'caller','file':source.relative,'line':source.tokens[i].line},
                            _event(caller,field,'forwarded-field'),_event(caller,provider_field,'typed-provider'),*proof]
        return []

    def prove(self, description, owned_files):
        parsed=re.fullmatch(r'\s*([\w$]+)\.([\w$]+)(?:\(\))?\s*(?:→|←|->|<-)\s*([\w$]+)\.([\w$]+)(?:\(\))?\s*',description)
        if not parsed: return self.fail('Unsupported integration point syntax')
        caller_name,handler,target_name,member_name=parsed.groups()
        caller=self.definition(caller_name)
        targets=[d for d in self.definitions if d.name == target_name and d.source.relative in owned_files]
        target=_one(targets)
        if caller is None or target is None:
            return self.fail('Caller or owned target definition is missing or ambiguous')
        handler_member=_one(caller.members.get(handler,[]))
        member=_one(target.members.get(member_name,[]))
        if handler_member is None or member is None:
            return self.fail('Caller handler/state or exact target member is missing or ambiguous')
        vals=caller.source.values
        evidence=self._typed_scalar_write(caller,handler_member,target,member)
        for i in range(caller.start+1,caller.end):
            if evidence: break
            # Static access must bind the imported (or same-file) class to the
            # exact owned definition, and the member must really be static.
            if vals[i:i+3] == [target_name,'.',member_name] and member.static:
                if (self.definition(target_name,caller.source) == target
                        and not self._shadowed_parameter(caller.source,target_name,caller.start,caller.end)
                        and self._consumed(caller,member,i+3)
                        and self._handler_link(caller,handler_member,i,None,i+3)):
                    evidence=[{'role':'caller','file':caller.source.relative,'line':caller.source.tokens[i].line},
                              *self._handler_chain(caller,handler_member,i),_event(target,member,'definition')]
                    break
            # A planned method/getter may call its own exact member without
            # instantiating another copy of its component/service.
            if (caller==target and vals[i:i+3]==['this','.',member_name] and not member.static
                    and self._consumed(caller,member,i+3)
                    and self._handler_link(caller,handler_member,i,None,i+3)):
                evidence=[{'role':'same-class-call','file':caller.source.relative,'line':caller.source.tokens[i].line},
                    _event(caller,handler_member,'handler-definition'),
                    *self._handler_chain(caller,handler_member,i),_event(target,member,'definition')]
                break
            # Shared service chains must resolve the imported live export,
            # interface slot and the exact real producer, not a global name.
            if (IDENT.fullmatch(vals[i]) and i+5<caller.end and vals[i+1]=='.' and vals[i+3]=='.'
                    and vals[i+4]==member_name and not member.static):
                binding=self._binding_slot(caller.source,vals[i],vals[i+2])
                if (binding and binding[0]==target and self._consumed(caller,member,i+5)
                        and self._handler_link(caller,handler_member,i,None,i+5)
                        and not self._shadowed_parameter(caller.source,vals[i],caller.start,caller.end)):
                    evidence=[{'role':'shared-service-call','file':caller.source.relative,'line':caller.source.tokens[i].line},
                        *self._handler_chain(caller,handler_member,i),*binding[1],_event(target,member,'definition')]
                    break
            if vals[i:i+2] != ['this','.'] or i+3 >= caller.end: continue
            field=_one(caller.members.get(vals[i+2],[]))
            if field is None or field.kind != 'field': continue
            owner=self.member_type(caller,field)
            if owner is None: continue
            cursor=i+3
            if vals[cursor] in {'!','?'}: cursor+=1
            if vals[cursor] != '.': continue
            value=vals[cursor+1]
            if (owner == target and value == member_name and not member.static
                    and self._consumed(caller,member,cursor+2)
                    and self._handler_link(caller,handler_member,i,field.name,cursor+2)):
                evidence=[{'role':'caller','file':caller.source.relative,'line':caller.source.tokens[i].line},_event(caller,field,'typed-field'),_event(target,member,'definition')]
                break
            provider=_one(owner.members.get(value,[]))
            if provider is None: continue
            proof=self._provider(owner,provider,target)
            if not proof: continue
            cursor+=2
            if vals[cursor] in {'!','?'}: cursor+=1
            if (vals[cursor:cursor+2] == ['.',member_name] and not member.static
                    and self._consumed(caller,member,cursor+2)
                    and self._handler_link(caller,handler_member,i,field.name,cursor+2)):
                evidence=[{'role':'caller','file':caller.source.relative,'line':caller.source.tokens[i].line},_event(caller,field,'typed-field'),_event(owner,provider,'provider'),*proof,_event(target,member,'definition')]
                break
        if not evidence and not member.static:
            evidence=self._self_provider_calls(caller,handler_member,target,member)
        if not evidence and not member.static:
            evidence=self._parameter_calls(caller,handler_member,target,member)
        if not evidence and handler_member.kind=='field' and self.member_type(caller,handler_member)==target:
            evidence=self._forwarded_field(caller,handler_member,target,member)
        if not evidence:
            return self.fail('No bound static/member access found; unsupported or ambiguous forms require review')
        return {'status':'PASS','caller':caller.source.relative,'evidence':evidence}

    @staticmethod
    def _consumed(caller, member, cursor, source=None):
        values=(source or caller.source).values
        if cursor >= len(values): return False
        return values[cursor] == '(' if member.kind == 'method' else values[cursor] not in {'=',':'}

    @staticmethod
    def fail(reason):
        return {'status':'FAIL','failed_check':'C2_NATIVE_BOUND_CALL_MISSING','reason':reason,
                'repair_action':'Connect the actual caller to the declared target member, or provide an unambiguous typed native provider; do not add an unused instance.', 'evidence':[]}
