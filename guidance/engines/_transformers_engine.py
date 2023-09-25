import time
import collections
import os
import torch
from ._local_engine import LocalEngine

class TransformersEngine(LocalEngine):
    def __init__(self, model=None, tokenizer=None, caching=True, temperature=0.0, device=None, **kwargs):
        
        # fill in default model value
        if model is None:
            model = os.environ.get("TRANSFORMERS_MODEL", None)
        if model is None:
            try:
                with open(os.path.expanduser('~/.transformers_model'), 'r') as file:
                    model = file.read().replace('\n', '')
            except:
                pass

        self.model_obj, self._orig_tokenizer = self._model_and_tokenizer(model, tokenizer, **kwargs)

        if not isinstance(model, str):
            self.model = model.__class__.__name__
        self.caching = caching
        self.current_time = time.time()
        self.call_history = collections.deque()
        self.temperature = temperature
        if device is not None: # set the device if requested
            self.model_obj = self.model_obj.to(device)
        self.device = self.model_obj.device # otherwise note the current device
        self._past_key_values = None

        # note that we convert the standard GPT and Llama special separators to spaces TODO: move this to subclasses
        super().__init__(
            [self._orig_tokenizer.convert_ids_to_tokens(i).replace(self.leading_space_token, " ") for i in range(self._orig_tokenizer.vocab_size)],
            self._orig_tokenizer.bos_token_id
        )

    def _model_and_tokenizer(self, model, tokenizer, **kwargs):

        # intantiate the model and tokenizer if needed
        if isinstance(model, str):

            # make sure transformers is installed
            try:
                import transformers
            except:
                raise Exception("Please install transformers with `pip install transformers` in order to use guidance.llms.Transformers!")

            if tokenizer is None:
                tokenizer = transformers.AutoTokenizer.from_pretrained(model, **kwargs)
            model = transformers.AutoModelForCausalLM.from_pretrained(model, **kwargs)
        
        assert tokenizer is not None, "You must give a tokenizer object when you provide a model object (as opposed to just a model name)!"

        # discover how the model handles leading spaces
        tokens = tokenizer.encode("alpha ruby")
        raw_coded = ''.join([tokenizer.convert_ids_to_tokens(id) for id in tokens])
        recoded = tokenizer.decode(tokens)
        assert len(raw_coded) == len(recoded), "The tokenizer is changing the length of the string, so you need make a special subclass to handle this model!"
        self.leading_space_token = raw_coded[5]
            
        return model, tokenizer

    def extend_model(self, token_ids):
        '''Extends the current model with the given token ids.
        
        This overrides a method from the LocalEngine class that is used to get
        inference results from the model.
        '''

        # get the number of caches position we are using
        past_length = self._past_key_values[0][0].size(-2) if self._past_key_values is not None else 0

        # call the model
        model_out = self.model_obj(
            input_ids=torch.tensor(token_ids).unsqueeze(0),
            past_key_values=self._past_key_values,
            use_cache=True,
            position_ids=torch.arange(past_length, past_length+len(token_ids)).unsqueeze(0),
            attention_mask=torch.ones(1, past_length + len(token_ids)),
            token_type_ids=None
        )

        # save the results
        self._past_key_values = model_out.past_key_values
        self._logits = model_out.logits[0, -1, :]
        self._cache_token_ids.extend(token_ids)